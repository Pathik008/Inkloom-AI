"""Content submission, compliance analysis, and human approval routes."""
import uuid
from typing import List

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import TenantContext, require_permission
from app.database import get_db
from app.models import PermissionCode
from app.schemas import (
    AddCommentRequest,
    ApplyCorrectionsRequest,
    ApprovalDecisionRequest,
    AssignReviewerRequest,
    ContentRevisionRequest,
    ContentSubmissionCreateRequest,
    ContentSubmissionResponse,
    ContentSubmissionSummaryResponse,
    ReviewActionResponse,
    ReviewerUserResponse,
    SubmitForApprovalRequest,
)
from app.services import compliance_service

router = APIRouter()
reviewers_router = APIRouter()


@router.post(
    "",
    response_model=ContentSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit marketing text and run deterministic compliance analysis",
)
def submit_content(
    payload: ContentSubmissionCreateRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_CREATE)),
    db: Session = Depends(get_db),
):
    submission = compliance_service.submit_content(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        brand_kit_id=payload.brand_kit_id,
        title=payload.title,
        content_text=payload.content_text,
    )
    return compliance_service.submission_to_dict(submission)


@router.get("", response_model=List[ContentSubmissionSummaryResponse], summary="List content submissions")
def list_submissions(
    brand_kit_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None, description="Filter by status, e.g. PENDING_REVIEW, APPROVED, REJECTED"),
    limit: int = Query(default=100, ge=1, le=200),
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_REVIEW)),
    db: Session = Depends(get_db),
):
    rows = compliance_service.list_submissions(
        db, organisation_id=context.organisation.id, brand_kit_id=brand_kit_id, status_filter=status, limit=limit
    )
    out = []
    for s in rows:
        latest = s.analyses[-1] if s.analyses else None
        out.append(
            ContentSubmissionSummaryResponse(
                id=s.id,
                brand_kit_id=s.brand_kit_id,
                brand_kit_version_id=s.brand_kit_version_id,
                parent_submission_id=s.parent_submission_id,
                revision_number=s.revision_number,
                title=s.title,
                score=latest.score if latest else None,
                result=latest.result if latest else None,
                status=s.status,
                assigned_reviewer_id=s.assigned_reviewer_id,
                assigned_reviewer_name=s.assigned_reviewer.full_name if s.assigned_reviewer else None,
                reviewed_by_name=s.reviewed_by.full_name if s.reviewed_by else None,
                reviewed_at=s.reviewed_at,
                created_at=s.created_at,
            )
        )
    return out


@reviewers_router.get("", response_model=List[ReviewerUserResponse], summary="List eligible reviewers for this organisation")
@router.get("/reviewers", response_model=List[ReviewerUserResponse], summary="List eligible reviewers for this organisation")
def list_reviewers(
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_REVIEW)),
    db: Session = Depends(get_db),
):
    return compliance_service.list_eligible_reviewers(db, organisation_id=context.organisation.id)


@router.get("/{submission_id}", response_model=ContentSubmissionResponse, summary="Get submission, findings and comparison")
def get_submission(
    submission_id: uuid.UUID,
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_REVIEW)),
    db: Session = Depends(get_db),
):
    submission = compliance_service.get_submission_or_404(
        db, organisation_id=context.organisation.id, submission_id=submission_id
    )
    lineage = compliance_service.get_submission_lineage(
        db, organisation_id=context.organisation.id, submission=submission
    )
    return compliance_service.submission_to_dict(
        submission,
        comparison=compliance_service.build_comparison(db, submission),
        all_revisions=lineage,
    )


@router.post(
    "/{submission_id}/revisions",
    response_model=ContentSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save edited content as a new revision and re-run analysis",
)
def revise_content(
    submission_id: uuid.UUID,
    payload: ContentRevisionRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_CREATE)),
    db: Session = Depends(get_db),
):
    revision = compliance_service.revise_content(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        submission_id=submission_id,
        content_text=payload.content_text,
        title=payload.title,
    )
    lineage = compliance_service.get_submission_lineage(
        db, organisation_id=context.organisation.id, submission=revision
    )
    return compliance_service.submission_to_dict(
        revision,
        comparison=compliance_service.build_comparison(db, revision),
        all_revisions=lineage,
    )


@router.post(
    "/{submission_id}/apply-corrections",
    response_model=ContentSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Apply suggested corrections as a new revision and re-run analysis",
)
def apply_corrections(
    submission_id: uuid.UUID,
    payload: ApplyCorrectionsRequest | None = None,
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_CREATE)),
    db: Session = Depends(get_db),
):
    revision, report = compliance_service.apply_suggested_corrections(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        submission_id=submission_id,
        finding_ids=payload.finding_ids if payload else None,
    )
    lineage = compliance_service.get_submission_lineage(
        db, organisation_id=context.organisation.id, submission=revision
    )
    return compliance_service.submission_to_dict(
        revision,
        comparison=compliance_service.build_comparison(db, revision),
        correction_report={
            "applied_finding_ids": report["applied_finding_ids"],
            "skipped": report["skipped"],
        },
        all_revisions=lineage,
    )


@router.post(
    "/{submission_id}/submit-for-approval",
    response_model=ContentSubmissionResponse,
    summary="Submit marketing content for human review and approval",
)
def submit_for_approval(
    submission_id: uuid.UUID,
    payload: SubmitForApprovalRequest | None = None,
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_CREATE)),
    db: Session = Depends(get_db),
):
    submission = compliance_service.submit_for_approval(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        submission_id=submission_id,
        assigned_reviewer_id=payload.assigned_reviewer_id if payload else None,
        comments=payload.comments if payload else None,
    )
    lineage = compliance_service.get_submission_lineage(
        db, organisation_id=context.organisation.id, submission=submission
    )
    return compliance_service.submission_to_dict(
        submission,
        comparison=compliance_service.build_comparison(db, submission),
        all_revisions=lineage,
    )


@router.post(
    "/{submission_id}/assign-reviewer",
    response_model=ContentSubmissionResponse,
    summary="Assign a reviewer to a content submission",
)
def assign_reviewer(
    submission_id: uuid.UUID,
    payload: AssignReviewerRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_REVIEW)),
    db: Session = Depends(get_db),
):
    submission = compliance_service.assign_reviewer(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        submission_id=submission_id,
        reviewer_id=payload.reviewer_id,
    )
    lineage = compliance_service.get_submission_lineage(
        db, organisation_id=context.organisation.id, submission=submission
    )
    return compliance_service.submission_to_dict(
        submission,
        comparison=compliance_service.build_comparison(db, submission),
        all_revisions=lineage,
    )


@router.post(
    "/{submission_id}/decide",
    response_model=ContentSubmissionResponse,
    summary="Approve, reject, or request revisions on submitted marketing content",
)
def decide_approval(
    submission_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.APPROVAL_DECIDE)),
    db: Session = Depends(get_db),
):
    submission = compliance_service.decide_approval(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        submission_id=submission_id,
        decision=payload.decision,
        comments=payload.comments,
    )
    lineage = compliance_service.get_submission_lineage(
        db, organisation_id=context.organisation.id, submission=submission
    )
    return compliance_service.submission_to_dict(
        submission,
        comparison=compliance_service.build_comparison(db, submission),
        all_revisions=lineage,
    )


@router.post(
    "/{submission_id}/comments",
    response_model=ContentSubmissionResponse,
    summary="Add a reviewer comment or note to a content submission",
)
def add_comment(
    submission_id: uuid.UUID,
    payload: AddCommentRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_REVIEW)),
    db: Session = Depends(get_db),
):
    submission = compliance_service.add_comment(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        submission_id=submission_id,
        comments=payload.comments,
    )
    lineage = compliance_service.get_submission_lineage(
        db, organisation_id=context.organisation.id, submission=submission
    )
    return compliance_service.submission_to_dict(
        submission,
        comparison=compliance_service.build_comparison(db, submission),
        all_revisions=lineage,
    )
