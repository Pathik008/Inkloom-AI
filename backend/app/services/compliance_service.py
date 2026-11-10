"""Content submission, deterministic analysis, correction, human approval and review workflow."""
import uuid
from datetime import datetime, timezone
from typing import Any, List

from fastapi import HTTPException, status
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    ApprovedBrandFact,
    BrandAuditLog,
    BrandKit,
    BrandKitVersion,
    BrandKitVersionStatus,
    ComplianceAnalysis,
    ComplianceRule,
    ContentReviewAction,
    ContentSubmission,
    FactCategory,
    FactRuleApprovalStatus,
    MembershipStatus,
    OrganisationMembership,
    PermissionCode,
    ReviewActionType,
    Role,
    RoleName,
    SubmissionStatus,
    User,
)
from app.models.brand import utcnow
from app.services import brand_kit_service
from app.services import compliance_engine as engine


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def resolve_published_version(db: Session, *, organisation_id: uuid.UUID, brand_kit_id: uuid.UUID) -> BrandKitVersion:
    """Return the kit's active PUBLISHED version (or its sole PUBLISHED version)."""
    kit = brand_kit_service.get_brand_kit_or_404(db, organisation_id=organisation_id, brand_kit_id=brand_kit_id)
    if kit.is_archived:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Brand Kit is archived.")
    version = None
    if kit.active_version_id:
        version = db.execute(
            select(BrandKitVersion).where(
                BrandKitVersion.id == kit.active_version_id,
                BrandKitVersion.organisation_id == organisation_id,
                BrandKitVersion.status == BrandKitVersionStatus.PUBLISHED,
            )
        ).scalar_one_or_none()
    if version is None:
        version = db.execute(
            select(BrandKitVersion).where(
                BrandKitVersion.brand_kit_id == kit.id,
                BrandKitVersion.organisation_id == organisation_id,
                BrandKitVersion.status == BrandKitVersionStatus.PUBLISHED,
            )
        ).scalar_one_or_none()
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This Brand Kit has no PUBLISHED version. Approve its rules and publish a version first.",
        )
    return version


def _load_rule_specs(db: Session, version: BrandKitVersion) -> list[engine.RuleSpec]:
    now = datetime.now(timezone.utc)
    rows = db.execute(
        select(ComplianceRule)
        .where(
            ComplianceRule.brand_kit_version_id == version.id,
            ComplianceRule.organisation_id == version.organisation_id,
            ComplianceRule.approval_status == FactRuleApprovalStatus.APPROVED,
            ComplianceRule.is_active.is_(True),
        )
        .order_by(ComplianceRule.priority.asc(), ComplianceRule.rule_code.asc())
    ).scalars()
    specs = []
    for r in rows:
        if _aware(r.effective_from) and _aware(r.effective_from) > now:
            continue
        if _aware(r.effective_to) and _aware(r.effective_to) < now:
            continue
        specs.append(
            engine.RuleSpec(
                id=str(r.id),
                rule_code=r.rule_code,
                rule_type=r.rule_type,
                severity=r.severity,
                title=r.title,
                description=r.description,
                target_pattern=r.target_pattern,
                match_mode=r.match_mode,
                required_disclaimer_text=r.required_disclaimer_text,
                suggested_replacement=r.suggested_replacement,
                config=dict(r.rule_config_json or {}),
            )
        )
    return specs


def _approved_prices(db: Session, version: BrandKitVersion) -> list[str]:
    facts = db.execute(
        select(ApprovedBrandFact.fact_value).where(
            ApprovedBrandFact.brand_kit_version_id == version.id,
            ApprovedBrandFact.organisation_id == version.organisation_id,
            ApprovedBrandFact.category == FactCategory.PRICING,
            ApprovedBrandFact.approval_status == FactRuleApprovalStatus.APPROVED,
            ApprovedBrandFact.is_active.is_(True),
        )
    ).scalars()
    prices: list[str] = []
    for value in facts:
        prices.extend(engine._extract_prices(value or ""))
    return prices


def _run_analysis(
    db: Session,
    submission: ContentSubmission,
    version: BrandKitVersion,
    *,
    mode: str = "deterministic",
    include_experimental_score: bool = False,
    llm_provider: Any = None,
) -> ComplianceAnalysis:
    if mode == "hybrid":
        from app.services.ai_workflow.compliance_graph import (
            ComplianceReviewWorkflow,
            WorkflowState,
        )

        try:
            workflow = ComplianceReviewWorkflow(db)
            state = WorkflowState(
                submission_id=submission.id,
                organisation_id=submission.organisation_id,
                brand_kit_version_id=version.id,
                raw_text=submission.content_text,
                mode=mode,
                llm_provider=llm_provider,
                include_experimental_score=include_experimental_score,
            )
            res_state = workflow.execute_sync(state)
        except (ValueError, engine.RuleDefinitionError) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

        analysis = ComplianceAnalysis(
            id=uuid.uuid4(),
            submission_id=submission.id,
            organisation_id=submission.organisation_id,
            brand_kit_version_id=version.id,
            engine_version="1.0.0",
            score=res_state.final_score,
            result=res_state.final_result,
            rules_evaluated=res_state.rules_evaluated,
            findings_json=res_state.final_findings,
            scoring_json=res_state.final_scoring_json,
        )
        db.add(analysis)
        return analysis

    # Standard deterministic analysis
    try:
        result = engine.analyze(
            submission.content_text,
            _load_rule_specs(db, version),
            approved_prices=_approved_prices(db, version),
        )
    except (ValueError, engine.RuleDefinitionError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    analysis = ComplianceAnalysis(
        id=uuid.uuid4(),
        submission_id=submission.id,
        organisation_id=submission.organisation_id,
        brand_kit_version_id=version.id,
        engine_version=result["engine_version"],
        score=result["score"],
        result=result["result"],
        rules_evaluated=result["rules_evaluated"],
        findings_json=result["findings"],
        scoring_json=result["scoring"],
    )
    db.add(analysis)
    return analysis


def _latest_analysis(submission: ContentSubmission) -> ComplianceAnalysis | None:
    return submission.analyses[-1] if submission.analyses else None


def _log_audit(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    brand_kit_version_id: uuid.UUID,
    action: str,
    submission_id: uuid.UUID,
    details: dict[str, Any],
) -> None:
    audit = BrandAuditLog(
        id=uuid.uuid4(),
        organisation_id=organisation_id,
        actor_user_id=user_id,
        brand_kit_id=brand_kit_id,
        brand_kit_version_id=brand_kit_version_id,
        action=action,
        resource_type="CONTENT_SUBMISSION",
        resource_id=submission_id,
        details_json=details,
        created_at=utcnow(),
    )
    db.add(audit)


def analysis_to_dict(analysis: ComplianceAnalysis | None) -> dict[str, Any] | None:
    if analysis is None:
        return None
    return {
        "id": analysis.id,
        "submission_id": analysis.submission_id,
        "engine_version": analysis.engine_version,
        "score": analysis.score,
        "result": analysis.result,
        "rules_evaluated": analysis.rules_evaluated,
        "findings": analysis.findings_json,
        "scoring": analysis.scoring_json,
        "created_at": analysis.created_at,
    }


def get_submission_lineage(db: Session, *, organisation_id: uuid.UUID, submission: ContentSubmission) -> list[dict[str, Any]]:
    """Return all revisions in the same lineage, ordered by revision_number ascending."""
    # Find root
    curr: ContentSubmission | None = submission
    visited = set()
    root_id = submission.id
    while curr and curr.parent_submission_id and curr.id not in visited:
        visited.add(curr.id)
        parent = db.execute(
            select(ContentSubmission).where(
                ContentSubmission.id == curr.parent_submission_id,
                ContentSubmission.organisation_id == organisation_id,
            )
        ).scalar_one_or_none()
        if parent:
            root_id = parent.id
            curr = parent
        else:
            break

    # Fetch all connected revisions in this lineage
    all_subs = db.execute(
        select(ContentSubmission)
        .where(
            ContentSubmission.organisation_id == organisation_id,
            or_(
                ContentSubmission.id == root_id,
                ContentSubmission.parent_submission_id == root_id,
                ContentSubmission.parent_submission_id.is_not(None),
            ),
        )
        .order_by(ContentSubmission.revision_number.asc())
    ).scalars().all()

    # Filter to only those linked to this tree
    tree_ids = {root_id}
    changed = True
    while changed:
        changed = False
        for s in all_subs:
            if s.parent_submission_id in tree_ids and s.id not in tree_ids:
                tree_ids.add(s.id)
                changed = True

    lineage = [s for s in all_subs if s.id in tree_ids]
    lineage.sort(key=lambda s: s.revision_number)

    return [
        {
            "id": s.id,
            "revision_number": s.revision_number,
            "title": s.title,
            "status": s.status,
            "score": s.analyses[-1].score if s.analyses else None,
            "result": s.analyses[-1].result if s.analyses else None,
            "created_at": s.created_at,
        }
        for s in lineage
    ]


def submission_to_dict(
    submission: ContentSubmission,
    *,
    comparison: dict[str, Any] | None = None,
    correction_report: dict[str, Any] | None = None,
    all_revisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    review_actions = [
        {
            "id": a.id,
            "submission_id": a.submission_id,
            "actor_user_id": a.actor_user_id,
            "actor_name": a.actor.full_name if a.actor else None,
            "actor_email": a.actor.email if a.actor else None,
            "action": a.action,
            "comments": a.comments,
            "created_at": a.created_at,
        }
        for a in (submission.review_actions or [])
    ]

    return {
        "id": submission.id,
        "organisation_id": submission.organisation_id,
        "brand_kit_id": submission.brand_kit_id,
        "brand_kit_version_id": submission.brand_kit_version_id,
        "parent_submission_id": submission.parent_submission_id,
        "revision_number": submission.revision_number,
        "title": submission.title,
        "content_text": submission.content_text,
        "submitted_by_user_id": submission.submitted_by_user_id,
        "submitted_by_name": submission.submitter.full_name if submission.submitter else None,
        "created_at": submission.created_at,
        "status": submission.status,
        "assigned_reviewer_id": submission.assigned_reviewer_id,
        "assigned_reviewer_name": submission.assigned_reviewer.full_name if submission.assigned_reviewer else None,
        "reviewed_by_user_id": submission.reviewed_by_user_id,
        "reviewed_by_name": submission.reviewed_by.full_name if submission.reviewed_by else None,
        "reviewed_at": submission.reviewed_at,
        "reviewer_comments": submission.reviewer_comments,
        "analysis": analysis_to_dict(_latest_analysis(submission)),
        "comparison": comparison,
        "correction_report": correction_report,
        "review_history": review_actions,
        "all_revisions": all_revisions or [],
    }


def submit_content(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    title: str,
    content_text: str,
    mode: str = "deterministic",
    include_experimental_score: bool = False,
    llm_provider: Any = None,
) -> ContentSubmission:
    version = resolve_published_version(db, organisation_id=organisation_id, brand_kit_id=brand_kit_id)
    submission = ContentSubmission(
        id=uuid.uuid4(),
        organisation_id=organisation_id,
        brand_kit_id=brand_kit_id,
        brand_kit_version_id=version.id,
        revision_number=1,
        title=title.strip(),
        content_text=content_text,
        submitted_by_user_id=user_id,
        status=SubmissionStatus.DRAFT,
    )
    db.add(submission)
    db.flush()
    _run_analysis(
        db,
        submission,
        version,
        mode=mode,
        include_experimental_score=include_experimental_score,
        llm_provider=llm_provider,
    )

    _log_audit(
        db,
        organisation_id=organisation_id,
        user_id=user_id,
        brand_kit_id=brand_kit_id,
        brand_kit_version_id=version.id,
        action="CONTENT_CREATED",
        submission_id=submission.id,
        details={"title": submission.title, "revision_number": 1, "status": SubmissionStatus.DRAFT},
    )

    db.commit()
    db.refresh(submission)
    return submission


def get_submission_or_404(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    submission_id: uuid.UUID,
    for_update: bool = False,
) -> ContentSubmission:
    stmt = (
        select(ContentSubmission)
        .options(
            joinedload(ContentSubmission.submitter),
            joinedload(ContentSubmission.assigned_reviewer),
            joinedload(ContentSubmission.reviewed_by),
            joinedload(ContentSubmission.review_actions).joinedload(ContentReviewAction.actor),
        )
        .where(
            ContentSubmission.id == submission_id,
            ContentSubmission.organisation_id == organisation_id,
        )
    )
    if for_update:
        bind = getattr(db, "bind", None) or (db.get_bind() if hasattr(db, "get_bind") else None)
        if bind and getattr(bind, "dialect", None) and bind.dialect.name == "postgresql":
            stmt = stmt.with_for_update(of=ContentSubmission)
    submission = db.execute(stmt).unique().scalar_one_or_none()
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content submission not found.")
    return submission


def list_submissions(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    brand_kit_id: uuid.UUID | None = None,
    status_filter: str | None = None,
    limit: int = 100,
) -> List[ContentSubmission]:
    stmt = (
        select(ContentSubmission)
        .options(
            joinedload(ContentSubmission.submitter),
            joinedload(ContentSubmission.assigned_reviewer),
            joinedload(ContentSubmission.reviewed_by),
        )
        .where(ContentSubmission.organisation_id == organisation_id)
    )
    if brand_kit_id:
        stmt = stmt.where(ContentSubmission.brand_kit_id == brand_kit_id)
    if status_filter:
        stmt = stmt.where(ContentSubmission.status == status_filter.strip().upper())
    stmt = stmt.order_by(ContentSubmission.created_at.desc()).limit(max(1, min(limit, 200)))
    return list(db.execute(stmt).unique().scalars().all())


def get_compliance_metrics(db: Session, *, organisation_id: uuid.UUID) -> dict[str, Any]:
    """Calculate aggregated submission counts using SQL aggregation (SEC-07)."""
    stmt = (
        select(
            func.count(ContentSubmission.id).label("total_submissions"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            ContentSubmission.status.in_(
                                [SubmissionStatus.PENDING_REVIEW, SubmissionStatus.UNDER_REVIEW]
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("pending_submissions"),
            func.coalesce(
                func.sum(
                    case(
                        (ContentSubmission.status == SubmissionStatus.APPROVED, 1),
                        else_=0,
                    )
                ),
                0,
            ).label("approved_submissions"),
            func.coalesce(
                func.sum(
                    case(
                        (ContentSubmission.status == SubmissionStatus.REJECTED, 1),
                        else_=0,
                    )
                ),
                0,
            ).label("rejected_submissions"),
            func.coalesce(
                func.sum(
                    case(
                        (ContentSubmission.status == SubmissionStatus.CHANGES_REQUESTED, 1),
                        else_=0,
                    )
                ),
                0,
            ).label("changes_requested_submissions"),
            func.coalesce(
                func.sum(
                    case(
                        (ContentSubmission.status == SubmissionStatus.DRAFT, 1),
                        else_=0,
                    )
                ),
                0,
            ).label("draft_submissions"),
        )
        .where(ContentSubmission.organisation_id == organisation_id)
    )
    row = db.execute(stmt).one()

    total = int(row.total_submissions or 0)
    pending = int(row.pending_submissions or 0)
    approved = int(row.approved_submissions or 0)
    rejected = int(row.rejected_submissions or 0)
    changes_requested = int(row.changes_requested_submissions or 0)
    draft = int(row.draft_submissions or 0)

    return {
        "organisation_id": organisation_id,
        "total_submissions": total,
        "pending_submissions": pending,
        "approved_submissions": approved,
        "rejected_submissions": rejected,
        "changes_requested_submissions": changes_requested,
        "draft_submissions": draft,
        "total": total,
        "pending_review": pending,
        "approved": approved,
        "rejected": rejected,
        "changes_requested": changes_requested,
        "draft": draft,
    }


def list_eligible_reviewers(db: Session, *, organisation_id: uuid.UUID) -> list[dict[str, Any]]:
    """Return all active organisation members who hold REVIEWER or ADMIN privileges."""
    stmt = (
        select(User, Role)
        .join(OrganisationMembership, OrganisationMembership.user_id == User.id)
        .join(Role, Role.id == OrganisationMembership.role_id)
        .where(
            OrganisationMembership.organisation_id == organisation_id,
            OrganisationMembership.status == MembershipStatus.ACTIVE,
            User.is_active.is_(True),
            Role.name.in_([RoleName.ADMIN, RoleName.REVIEWER]),
        )
        .order_by(User.full_name.asc())
    )
    rows = db.execute(stmt).all()
    return [
        {
            "id": u.id,
            "full_name": u.full_name,
            "email": u.email,
            "role": r.name,
        }
        for u, r in rows
    ]


def submit_for_approval(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    submission_id: uuid.UUID,
    assigned_reviewer_id: uuid.UUID | None = None,
    comments: str | None = None,
) -> ContentSubmission:
    """Submit a draft or revised submission for human approval."""
    submission = get_submission_or_404(
        db,
        organisation_id=organisation_id,
        submission_id=submission_id,
        for_update=True,
    )

    if submission.status not in (SubmissionStatus.DRAFT, SubmissionStatus.CHANGES_REQUESTED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot submit submission in '{submission.status}' status for approval. Allowed states are DRAFT and CHANGES_REQUESTED.",
        )

    # Validate assigned reviewer if provided
    if assigned_reviewer_id:
        if assigned_reviewer_id == submission.submitted_by_user_id or assigned_reviewer_id == user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Independent review required: Submitter cannot be assigned as the reviewer.",
            )
        rev_membership = db.execute(
            select(OrganisationMembership, Role)
            .join(Role, Role.id == OrganisationMembership.role_id)
            .where(
                OrganisationMembership.organisation_id == organisation_id,
                OrganisationMembership.user_id == assigned_reviewer_id,
                OrganisationMembership.status == MembershipStatus.ACTIVE,
            )
        ).first()
        if not rev_membership:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assigned reviewer is not an active member.")
        _mem, role = rev_membership
        if role.name not in (RoleName.ADMIN, RoleName.REVIEWER):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target reviewer does not hold approval authority (must be ADMIN or REVIEWER).",
            )
        submission.assigned_reviewer_id = assigned_reviewer_id

    try:
        submission.status = SubmissionStatus.PENDING_REVIEW

        action = ContentReviewAction(
            id=uuid.uuid4(),
            submission_id=submission.id,
            organisation_id=organisation_id,
            actor_user_id=user_id,
            action=ReviewActionType.SUBMIT_FOR_APPROVAL,
            comments=comments,
        )
        db.add(action)

        _log_audit(
            db,
            organisation_id=organisation_id,
            user_id=user_id,
            brand_kit_id=submission.brand_kit_id,
            brand_kit_version_id=submission.brand_kit_version_id,
            action="CONTENT_SUBMITTED_FOR_APPROVAL",
            submission_id=submission.id,
            details={
                "revision_number": submission.revision_number,
                "assigned_reviewer_id": str(assigned_reviewer_id) if assigned_reviewer_id else None,
                "comments": comments,
            },
        )

        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(submission)
    return submission


def assign_reviewer(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    submission_id: uuid.UUID,
    reviewer_id: uuid.UUID,
) -> ContentSubmission:
    submission = get_submission_or_404(
        db,
        organisation_id=organisation_id,
        submission_id=submission_id,
        for_update=True,
    )

    if submission.status in (SubmissionStatus.APPROVED, SubmissionStatus.REJECTED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot assign reviewer to submission in '{submission.status}' status.",
        )

    # SEC: Prevent author from being assigned as their own reviewer
    if reviewer_id == submission.submitted_by_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Independent review required: Submitter cannot be assigned as the reviewer.",
        )

    rev_membership = db.execute(
        select(OrganisationMembership, Role)
        .join(Role, Role.id == OrganisationMembership.role_id)
        .where(
            OrganisationMembership.organisation_id == organisation_id,
            OrganisationMembership.user_id == reviewer_id,
            OrganisationMembership.status == MembershipStatus.ACTIVE,
        )
    ).first()
    if not rev_membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target reviewer is not an active member.")

    _mem, role = rev_membership
    if role.name not in (RoleName.ADMIN, RoleName.REVIEWER):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target reviewer does not hold approval authority (must be ADMIN or REVIEWER).",
        )

    try:
        submission.assigned_reviewer_id = reviewer_id
        if submission.status == SubmissionStatus.DRAFT:
            submission.status = SubmissionStatus.PENDING_REVIEW

        action = ContentReviewAction(
            id=uuid.uuid4(),
            submission_id=submission.id,
            organisation_id=organisation_id,
            actor_user_id=user_id,
            action=ReviewActionType.ASSIGN_REVIEWER,
            comments=f"Assigned reviewer {reviewer_id}",
        )
        db.add(action)

        _log_audit(
            db,
            organisation_id=organisation_id,
            user_id=user_id,
            brand_kit_id=submission.brand_kit_id,
            brand_kit_version_id=submission.brand_kit_version_id,
            action="CONTENT_REVIEWER_ASSIGNED",
            submission_id=submission.id,
            details={"assigned_reviewer_id": str(reviewer_id)},
        )

        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(submission)
    return submission


def decide_approval(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    submission_id: uuid.UUID,
    decision: str,
    comments: str | None = None,
) -> ContentSubmission:
    decision = decision.strip().upper()
    if decision not in ("APPROVE", "REJECT", "REQUEST_CHANGES"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Decision must be APPROVE, REJECT, or REQUEST_CHANGES.",
        )

    submission = get_submission_or_404(
        db,
        organisation_id=organisation_id,
        submission_id=submission_id,
        for_update=True,
    )

    if submission.status not in (SubmissionStatus.PENDING_REVIEW, SubmissionStatus.UNDER_REVIEW):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot decide approval on submission in '{submission.status}' status. Only PENDING_REVIEW or UNDER_REVIEW submissions may be decided.",
        )

    # SEC-08: Strict Maker-Checker Principle Enforcement
    # The submitter/author of a compliance submission cannot approve, reject, or decide on their own copy.
    if submission.submitted_by_user_id == user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Independent review required: Submitter cannot approve their own submission.",
        )

    if decision == "APPROVE":
        target_status = SubmissionStatus.APPROVED
        action_type = ReviewActionType.APPROVE
        audit_action = "CONTENT_APPROVED"
    elif decision == "REJECT":
        target_status = SubmissionStatus.REJECTED
        action_type = ReviewActionType.REJECT
        audit_action = "CONTENT_REJECTED"
    else:
        target_status = SubmissionStatus.CHANGES_REQUESTED
        action_type = ReviewActionType.REQUEST_CHANGES
        audit_action = "CONTENT_CHANGES_REQUESTED"

    try:
        submission.status = target_status
        submission.reviewed_by_user_id = user_id
        submission.reviewed_at = utcnow()
        submission.reviewer_comments = comments

        action = ContentReviewAction(
            id=uuid.uuid4(),
            submission_id=submission.id,
            organisation_id=organisation_id,
            actor_user_id=user_id,
            action=action_type,
            comments=comments,
        )
        db.add(action)

        _log_audit(
            db,
            organisation_id=organisation_id,
            user_id=user_id,
            brand_kit_id=submission.brand_kit_id,
            brand_kit_version_id=submission.brand_kit_version_id,
            action=audit_action,
            submission_id=submission.id,
            details={"decision": decision, "comments": comments, "revision_number": submission.revision_number},
        )

        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(submission)
    return submission


def add_comment(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    submission_id: uuid.UUID,
    comments: str,
) -> ContentSubmission:
    submission = get_submission_or_404(db, organisation_id=organisation_id, submission_id=submission_id)
    try:
        action = ContentReviewAction(
            id=uuid.uuid4(),
            submission_id=submission.id,
            organisation_id=organisation_id,
            actor_user_id=user_id,
            action=ReviewActionType.COMMENT,
            comments=comments.strip(),
        )
        db.add(action)

        _log_audit(
            db,
            organisation_id=organisation_id,
            user_id=user_id,
            brand_kit_id=submission.brand_kit_id,
            brand_kit_version_id=submission.brand_kit_version_id,
            action="CONTENT_COMMENT_ADDED",
            submission_id=submission.id,
            details={"comments": comments.strip()},
        )

        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(submission)
    return submission


def build_comparison(db: Session, submission: ContentSubmission) -> dict[str, Any] | None:
    if submission.parent_submission_id is None:
        return None
    parent = get_submission_or_404(
        db, organisation_id=submission.organisation_id, submission_id=submission.parent_submission_id
    )
    before, after = _latest_analysis(parent), _latest_analysis(submission)
    if before is None or after is None:
        return None
    return engine.compare_analyses(
        parent.content_text,
        {"findings": before.findings_json, "score": before.score, "result": before.result},
        submission.content_text,
        {"findings": after.findings_json, "score": after.score, "result": after.result},
    )


def _create_revision(
    db: Session,
    *,
    parent: ContentSubmission,
    user_id: uuid.UUID,
    content_text: str,
    title: str | None,
) -> ContentSubmission:
    version = db.execute(
        select(BrandKitVersion).where(
            BrandKitVersion.id == parent.brand_kit_version_id,
            BrandKitVersion.organisation_id == parent.organisation_id,
        )
    ).scalar_one()
    revision = ContentSubmission(
        id=uuid.uuid4(),
        organisation_id=parent.organisation_id,
        brand_kit_id=parent.brand_kit_id,
        brand_kit_version_id=parent.brand_kit_version_id,
        parent_submission_id=parent.id,
        revision_number=parent.revision_number + 1,
        title=(title or parent.title).strip(),
        content_text=content_text,
        submitted_by_user_id=user_id,
        status=SubmissionStatus.DRAFT,
        assigned_reviewer_id=parent.assigned_reviewer_id,
    )
    db.add(revision)
    db.flush()
    _run_analysis(db, revision, version)

    _log_audit(
        db,
        organisation_id=parent.organisation_id,
        user_id=user_id,
        brand_kit_id=parent.brand_kit_id,
        brand_kit_version_id=version.id,
        action="CONTENT_REVISED",
        submission_id=revision.id,
        details={
            "revision_number": revision.revision_number,
            "parent_submission_id": str(parent.id),
        },
    )

    db.commit()
    db.refresh(revision)
    return revision


def revise_content(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    submission_id: uuid.UUID,
    content_text: str,
    title: str | None,
) -> ContentSubmission:
    parent = get_submission_or_404(db, organisation_id=organisation_id, submission_id=submission_id)
    return _create_revision(db, parent=parent, user_id=user_id, content_text=content_text, title=title)


def apply_suggested_corrections(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    submission_id: uuid.UUID,
    finding_ids: list[str] | None,
) -> tuple[ContentSubmission, dict[str, Any]]:
    parent = get_submission_or_404(db, organisation_id=organisation_id, submission_id=submission_id)
    analysis = _latest_analysis(parent)
    if analysis is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Submission has no analysis.")
    known = {f["finding_id"] for f in analysis.findings_json}
    wanted = set(finding_ids) if finding_ids is not None else None
    if wanted is not None and not wanted <= known:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown finding_id for this submission."
        )
    report = engine.apply_corrections(parent.content_text, analysis.findings_json, wanted)
    if not report["applied_finding_ids"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="None of the selected findings has an automatic correction. Edit the content manually.",
        )
    revision = _create_revision(
        db, parent=parent, user_id=user_id, content_text=report["corrected_text"], title=None
    )
    return revision, report
