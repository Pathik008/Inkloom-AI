"""Test suite for Phase 5.2 Approvals Queue API contracts, review actions, and workflow.

Verifies:
1. Approvals queue listing and status filtering (PENDING_REVIEW, UNDER_REVIEW, APPROVED, REJECTED, CHANGES_REQUESTED).
2. Fetching detailed submission with compliance findings and cited evidence.
3. Reviewer action execution: APPROVE, REJECT, and REQUEST_CHANGES.
4. Reviewer note/comment posting (`/comments`).
5. Prevention of invalid decisions or actions by non-authorised roles:
   - ADMIN and REVIEWER can access queue and decide approvals.
   - BRAND_MANAGER can read queue (content:review) but cannot decide approvals (403 Forbidden).
   - CONTENT_CREATOR can read queue (content:review) but cannot decide approvals (403 Forbidden).
6. Reviewer assignment API contract (`/assign-reviewer`).
7. Organisation isolation across multiple reviewer queues.
"""
from __future__ import annotations

import uuid
from typing import Generator
import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.database import Base, get_db, init_db
from app.main import app
from app.models import (
    BrandKit,
    BrandKitVersion,
    BrandKitVersionStatus,
    ComplianceAnalysis,
    ContentReviewAction,
    ContentSubmission,
    Organisation,
    OrganisationMembership,
    Role,
    RoleName,
    SubmissionStatus,
    User,
)


@pytest.fixture
def sqlite_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    init_db(session=session)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def approval_fixture(sqlite_session: Session):
    db = sqlite_session
    admin_role = db.query(Role).filter(Role.name == RoleName.ADMIN).first()
    bm_role = db.query(Role).filter(Role.name == RoleName.BRAND_MANAGER).first()
    creator_role = db.query(Role).filter(Role.name == RoleName.CONTENT_CREATOR).first()
    reviewer_role = db.query(Role).filter(Role.name == RoleName.REVIEWER).first()

    admin_user = User(
        email=f"admin-{uuid.uuid4().hex[:6]}@inkloom.ai",
        full_name="Admin Reviewer",
        password_hash=hash_password("Pass123!"),
        is_active=True,
        is_verified=True,
    )
    bm_user = User(
        email=f"bm-{uuid.uuid4().hex[:6]}@inkloom.ai",
        full_name="Brand Manager User",
        password_hash=hash_password("Pass123!"),
        is_active=True,
        is_verified=True,
    )
    creator_user = User(
        email=f"creator-{uuid.uuid4().hex[:6]}@inkloom.ai",
        full_name="Creator Author",
        password_hash=hash_password("Pass123!"),
        is_active=True,
        is_verified=True,
    )
    reviewer_user = User(
        email=f"reviewer-{uuid.uuid4().hex[:6]}@inkloom.ai",
        full_name="Staff Reviewer",
        password_hash=hash_password("Pass123!"),
        is_active=True,
        is_verified=True,
    )
    db.add_all([admin_user, bm_user, creator_user, reviewer_user])
    db.flush()

    org = Organisation(
        name="Inkloom Approvals Org",
        slug=f"approvals-org-{uuid.uuid4().hex[:6]}",
        created_by=admin_user.id,
    )
    db.add(org)
    db.flush()

    db.add_all([
        OrganisationMembership(user_id=admin_user.id, organisation_id=org.id, role_id=admin_role.id, status="ACTIVE"),
        OrganisationMembership(user_id=bm_user.id, organisation_id=org.id, role_id=bm_role.id, status="ACTIVE"),
        OrganisationMembership(user_id=creator_user.id, organisation_id=org.id, role_id=creator_role.id, status="ACTIVE"),
        OrganisationMembership(user_id=reviewer_user.id, organisation_id=org.id, role_id=reviewer_role.id, status="ACTIVE"),
    ])

    kit = BrandKit(
        organisation_id=org.id,
        name="Acme Master Brand",
        slug="acme-master",
        created_by_user_id=admin_user.id,
    )
    db.add(kit)
    db.flush()

    ver = BrandKitVersion(
        brand_kit_id=kit.id,
        organisation_id=org.id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=admin_user.id,
    )
    db.add(ver)
    db.flush()

    ver.status = BrandKitVersionStatus.PUBLISHED
    ver.published_by_user_id = admin_user.id
    kit.active_version_id = ver.id
    db.flush()

    sub = ContentSubmission(
        organisation_id=org.id,
        brand_kit_id=kit.id,
        brand_kit_version_id=ver.id,
        submitted_by_user_id=creator_user.id,
        title="Spring Product Launch Press Release",
        content_text="Check out our guaranteed risk-free investments.",
        status=SubmissionStatus.PENDING_REVIEW,
    )
    db.add(sub)
    db.flush()

    analysis = ComplianceAnalysis(
        submission_id=sub.id,
        organisation_id=org.id,
        brand_kit_version_id=ver.id,
        engine_version="1.0.0",
        score=65,
        result="FAIL",
        rules_evaluated=5,
        findings_json=[{
            "finding_id": "f-1",
            "rule_code": "PROHIBITED_CLAIM",
            "rule_title": "Risk-Free Guarantee",
            "severity": "CRITICAL",
            "kind": "PROHIBITED_TERM",
            "matched_text": "risk-free",
            "start": 25,
            "end": 34,
            "evidence_excerpt": "guaranteed risk-free investments",
            "explanation": "Guarantees are strictly prohibited in retail financial promotions.",
            "recommended_correction": "Remove 'risk-free' guarantee.",
        }],
        scoring_json={"total_penalty": 35},
    )
    db.add(analysis)
    db.commit()

    return {
        "org": org,
        "admin": admin_user,
        "bm": bm_user,
        "creator": creator_user,
        "reviewer": reviewer_user,
        "submission": sub,
    }


@pytest.mark.anyio
async def test_approvals_queue_listing_and_detail(sqlite_session: Session, approval_fixture: dict):
    """Test approvals queue listing with status filtering and detailed submission inspection."""
    data = approval_fixture
    org = data["org"]
    reviewer = data["reviewer"]
    sub = data["submission"]

    def override_db():
        try:
            yield sqlite_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    tok, _, _ = create_access_token(subject=str(reviewer.id), email=reviewer.email)
    headers = {"Authorization": f"Bearer {tok}", "X-Organisation-ID": str(org.id)}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. List pending submissions
        resp = await client.get(
            f"/api/v1/organisations/{org.id}/compliance/submissions?status=PENDING_REVIEW",
            headers=headers,
        )
        assert resp.status_code == status.HTTP_200_OK
        items = resp.json()
        assert len(items) == 1
        assert items[0]["id"] == str(sub.id)
        assert items[0]["title"] == "Spring Product Launch Press Release"
        assert items[0]["score"] == 65
        assert items[0]["result"] == "FAIL"

        # 2. Inspect submission detail
        detail_resp = await client.get(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub.id}",
            headers=headers,
        )
        assert detail_resp.status_code == status.HTTP_200_OK
        detail = detail_resp.json()
        assert detail["id"] == str(sub.id)
        assert detail["analysis"]["score"] == 65
        assert len(detail["analysis"]["findings"]) == 1
        assert detail["analysis"]["findings"][0]["rule_code"] == "PROHIBITED_CLAIM"

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_reviewer_decision_workflow_actions(sqlite_session: Session, approval_fixture: dict):
    """Test full decision workflow: adding notes, requesting changes, and approving."""
    data = approval_fixture
    org = data["org"]
    reviewer = data["reviewer"]
    creator = data["creator"]
    bm = data["bm"]
    sub = data["submission"]

    def override_db():
        try:
            yield sqlite_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    tok_rev, _, _ = create_access_token(subject=str(reviewer.id), email=reviewer.email)
    h_rev = {"Authorization": f"Bearer {tok_rev}", "X-Organisation-ID": str(org.id)}

    tok_creator, _, _ = create_access_token(subject=str(creator.id), email=creator.email)
    h_creator = {"Authorization": f"Bearer {tok_creator}", "X-Organisation-ID": str(org.id)}

    tok_bm, _, _ = create_access_token(subject=str(bm.id), email=bm.email)
    h_bm = {"Authorization": f"Bearer {tok_bm}", "X-Organisation-ID": str(org.id)}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Add reviewer note
        comment_resp = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub.id}/comments",
            headers=h_rev,
            json={"comments": "Please remove all unapproved financial guarantee terms."},
        )
        assert comment_resp.status_code == status.HTTP_200_OK
        assert len(comment_resp.json()["review_history"]) == 1
        assert comment_resp.json()["review_history"][0]["action"] == "COMMENT"

        # 2. Content Creator cannot execute approval decisions (403 Forbidden)
        creator_decide = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub.id}/decide",
            headers=h_creator,
            json={"decision": "APPROVE"},
        )
        assert creator_decide.status_code == status.HTTP_403_FORBIDDEN

        # 3. Brand Manager can view queue but cannot decide approvals (403 Forbidden without approval:decide)
        bm_decide = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub.id}/decide",
            headers=h_bm,
            json={"decision": "APPROVE"},
        )
        assert bm_decide.status_code == status.HTTP_403_FORBIDDEN

        # 4. Reviewer executes REQUEST_CHANGES
        changes_resp = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub.id}/decide",
            headers=h_rev,
            json={"decision": "REQUEST_CHANGES", "comments": "Critical violations must be resolved first."},
        )
        assert changes_resp.status_code == status.HTTP_200_OK
        assert changes_resp.json()["status"] == "CHANGES_REQUESTED"

        # 4b. SEC-03: Attempting to decide a CHANGES_REQUESTED submission returns 409 Conflict
        conflict_decide = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub.id}/decide",
            headers=h_rev,
            json={"decision": "APPROVE", "comments": "Premature approval."},
        )
        assert conflict_decide.status_code == status.HTTP_409_CONFLICT

        # 4c. Author resubmits for approval: CHANGES_REQUESTED -> PENDING_REVIEW
        resubmit_resp = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub.id}/submit-for-approval",
            headers=h_creator,
            json={"comments": "Addressed feedback and updated claims."},
        )
        assert resubmit_resp.status_code == status.HTTP_200_OK
        assert resubmit_resp.json()["status"] == "PENDING_REVIEW"

        # 5. Reviewer executes final APPROVE
        approve_resp = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub.id}/decide",
            headers=h_rev,
            json={"decision": "APPROVE", "comments": "Exception approved for internal test."},
        )
        assert approve_resp.status_code == status.HTTP_200_OK
        assert approve_resp.json()["status"] == "APPROVED"
        assert approve_resp.json()["reviewed_by_name"] == "Staff Reviewer"

        # 6. SEC-03 Terminal state check: cannot decide on APPROVED submission (409 Conflict)
        reapprove_resp = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub.id}/decide",
            headers=h_rev,
            json={"decision": "REJECT"},
        )
        assert reapprove_resp.status_code == status.HTTP_409_CONFLICT

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_reviewer_assignment_endpoint(sqlite_session: Session, approval_fixture: dict):
    """Test assigning a reviewer via the backend assignment route."""
    data = approval_fixture
    org = data["org"]
    admin = data["admin"]
    reviewer = data["reviewer"]
    sub = data["submission"]

    def override_db():
        try:
            yield sqlite_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    tok_admin, _, _ = create_access_token(subject=str(admin.id), email=admin.email)
    h_admin = {"Authorization": f"Bearer {tok_admin}", "X-Organisation-ID": str(org.id)}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub.id}/assign-reviewer",
            headers=h_admin,
            json={"reviewer_id": str(reviewer.id)},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["assigned_reviewer_id"] == str(reviewer.id)
        assert data["assigned_reviewer_name"] == "Staff Reviewer"

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_strict_maker_checker_enforcement(sqlite_session: Session, approval_fixture: dict):
    """Test strict maker-checker enforcement:

    1. An ADMIN cannot approve their own submission (403 Forbidden).
    2. An ADMIN cannot reject their own submission (403 Forbidden).
    3. A REVIEWER can approve another user's submission (200 OK).
    4. A REVIEWER can reject another user's submission (200 OK).
    5. A user without approval:decide permission still receives 403 Forbidden.
    6. A reviewer from another organisation cannot decide the submission (403 or 404).
    7. A rejected self-approval attempt does not mutate submission status or add decision history.
    """
    db = sqlite_session
    data = approval_fixture
    org = data["org"]
    admin = data["admin"]
    reviewer = data["reviewer"]
    creator = data["creator"]
    bm = data["bm"]
    sub = data["submission"]

    # Create submission where ADMIN is the submitter
    brand_kit = db.query(BrandKit).filter(BrandKit.organisation_id == org.id).first()
    active_version = db.query(BrandKitVersion).filter(BrandKitVersion.brand_kit_id == brand_kit.id).first()

    admin_sub = ContentSubmission(
        id=uuid.uuid4(),
        organisation_id=org.id,
        brand_kit_id=brand_kit.id,
        brand_kit_version_id=active_version.id,
        revision_number=1,
        title="Admin Authored Press Release",
        content_text="Special terms apply for high net worth clients.",
        submitted_by_user_id=admin.id,
        status=SubmissionStatus.PENDING_REVIEW,
    )
    db.add(admin_sub)
    db.commit()

    def override_db():
        try:
            yield sqlite_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_db

    tok_admin, _, _ = create_access_token(subject=str(admin.id), email=admin.email)
    h_admin = {"Authorization": f"Bearer {tok_admin}", "X-Organisation-ID": str(org.id)}

    tok_rev, _, _ = create_access_token(subject=str(reviewer.id), email=reviewer.email)
    h_rev = {"Authorization": f"Bearer {tok_rev}", "X-Organisation-ID": str(org.id)}

    tok_bm, _, _ = create_access_token(subject=str(bm.id), email=bm.email)
    h_bm = {"Authorization": f"Bearer {tok_bm}", "X-Organisation-ID": str(org.id)}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. ADMIN attempts to APPROVE their own submission -> 403 Forbidden
        self_approve = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{admin_sub.id}/decide",
            headers=h_admin,
            json={"decision": "APPROVE", "comments": "Self approving my own copy."},
        )
        assert self_approve.status_code == status.HTTP_403_FORBIDDEN
        assert "Independent review required: Submitter cannot approve their own submission." in self_approve.json()["detail"]

        # 7. Verify status and history NOT mutated by failed self-approval attempt
        db.refresh(admin_sub)
        assert admin_sub.status == SubmissionStatus.PENDING_REVIEW
        actions = db.query(ContentReviewAction).filter(ContentReviewAction.submission_id == admin_sub.id).all()
        assert len(actions) == 0

        # 2. ADMIN attempts to REJECT their own submission -> 403 Forbidden
        self_reject = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{admin_sub.id}/decide",
            headers=h_admin,
            json={"decision": "REJECT", "comments": "Self rejecting my own copy."},
        )
        assert self_reject.status_code == status.HTTP_403_FORBIDDEN
        assert "Independent review required: Submitter cannot approve their own submission." in self_reject.json()["detail"]

        # 5. User without approval:decide permission (Brand Manager) receives 403
        bm_decide = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{admin_sub.id}/decide",
            headers=h_bm,
            json={"decision": "APPROVE"},
        )
        assert bm_decide.status_code == status.HTTP_403_FORBIDDEN
        assert "approval:decide" in bm_decide.json()["detail"]

        # 6. Reviewer from alien organisation cannot decide
        alien_org_id = uuid.uuid4()
        alien_decide = await client.post(
            f"/api/v1/organisations/{alien_org_id}/compliance/submissions/{admin_sub.id}/decide",
            headers=h_rev,
            json={"decision": "APPROVE"},
        )
        assert alien_decide.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)

        # 3. Independent REVIEWER approves Admin's submission -> 200 OK
        rev_approve = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{admin_sub.id}/decide",
            headers=h_rev,
            json={"decision": "APPROVE", "comments": "Independent reviewer verified."},
        )
        assert rev_approve.status_code == status.HTTP_200_OK
        assert rev_approve.json()["status"] == "APPROVED"
        assert rev_approve.json()["reviewed_by_name"] == "Staff Reviewer"

        # 4. Independent REVIEWER rejects Creator's submission -> 200 OK
        # sub is authored by creator
        rev_reject = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub.id}/decide",
            headers=h_rev,
            json={"decision": "REJECT", "comments": "Independent reviewer rejected claims."},
        )
        assert rev_reject.status_code == status.HTTP_200_OK
        assert rev_reject.json()["status"] == "REJECTED"

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_reviewer_assignment_rbac_and_self_assignment_prevention(sqlite_session: Session, approval_fixture: dict):
    """Test reviewer assignment RBAC and maker-checker validation:

    1. CONTENT_CREATOR cannot call /assign-reviewer (403 Forbidden).
    2. BRAND_MANAGER cannot call /assign-reviewer (403 Forbidden).
    3. Authorized ADMIN can call /assign-reviewer for an eligible independent reviewer (200 OK).
    4. Submitter cannot be assigned as their own reviewer via /assign-reviewer (400 Bad Request).
    5. Submitter cannot be assigned as their own reviewer via /submit-for-approval (400 Bad Request).
    6. Submitting for approval with selected eligible reviewer assigns them (200 OK).
    7. Submitting for approval without reviewer ID preserves Auto-assign (200 OK).
    8. Reviewer from another organisation cannot be assigned (404 Not Found).
    """
    db = sqlite_session
    data = approval_fixture
    org = data["org"]
    admin = data["admin"]
    reviewer = data["reviewer"]
    creator = data["creator"]
    bm = data["bm"]
    sub = data["submission"]

    def override_db():
        try:
            yield sqlite_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_db

    tok_admin, _, _ = create_access_token(subject=str(admin.id), email=admin.email)
    h_admin = {"Authorization": f"Bearer {tok_admin}", "X-Organisation-ID": str(org.id)}

    tok_rev, _, _ = create_access_token(subject=str(reviewer.id), email=reviewer.email)
    h_rev = {"Authorization": f"Bearer {tok_rev}", "X-Organisation-ID": str(org.id)}

    tok_creator, _, _ = create_access_token(subject=str(creator.id), email=creator.email)
    h_creator = {"Authorization": f"Bearer {tok_creator}", "X-Organisation-ID": str(org.id)}

    tok_bm, _, _ = create_access_token(subject=str(bm.id), email=bm.email)
    h_bm = {"Authorization": f"Bearer {tok_bm}", "X-Organisation-ID": str(org.id)}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. CONTENT_CREATOR cannot call /assign-reviewer -> 403 Forbidden
        r_cc = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub.id}/assign-reviewer",
            headers=h_creator,
            json={"reviewer_id": str(reviewer.id)},
        )
        assert r_cc.status_code == status.HTTP_403_FORBIDDEN
        assert "approval:decide" in r_cc.json()["detail"]

        # 2. BRAND_MANAGER cannot call /assign-reviewer -> 403 Forbidden
        r_bm = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub.id}/assign-reviewer",
            headers=h_bm,
            json={"reviewer_id": str(reviewer.id)},
        )
        assert r_bm.status_code == status.HTTP_403_FORBIDDEN
        assert "approval:decide" in r_bm.json()["detail"]

        # 3. Submitter cannot be assigned as their own reviewer via /assign-reviewer -> 400 Bad Request
        r_self_assign = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub.id}/assign-reviewer",
            headers=h_admin,
            json={"reviewer_id": str(creator.id)},
        )
        assert r_self_assign.status_code == status.HTTP_400_BAD_REQUEST
        assert "Independent review required: Submitter cannot be assigned as the reviewer." in r_self_assign.json()["detail"]

        # 4. Reviewer from another organisation cannot be assigned -> 404 Not Found
        r_alien = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub.id}/assign-reviewer",
            headers=h_admin,
            json={"reviewer_id": str(uuid.uuid4())},
        )
        assert r_alien.status_code == status.HTTP_404_NOT_FOUND

        # 5. Authorized ADMIN can assign independent reviewer -> 200 OK
        r_admin_assign = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub.id}/assign-reviewer",
            headers=h_admin,
            json={"reviewer_id": str(reviewer.id)},
        )
        assert r_admin_assign.status_code == status.HTTP_200_OK
        assert r_admin_assign.json()["assigned_reviewer_id"] == str(reviewer.id)

        # 6. Create a draft submission to test /submit-for-approval contracts
        brand_kit = db.query(BrandKit).filter(BrandKit.organisation_id == org.id).first()
        active_version = db.query(BrandKitVersion).filter(BrandKitVersion.brand_kit_id == brand_kit.id).first()

        draft_sub = ContentSubmission(
            id=uuid.uuid4(),
            organisation_id=org.id,
            brand_kit_id=brand_kit.id,
            brand_kit_version_id=active_version.id,
            revision_number=1,
            title="Draft Test Content",
            content_text="Sample text for testing submission.",
            submitted_by_user_id=creator.id,
            status=SubmissionStatus.DRAFT,
        )
        db.add(draft_sub)
        db.commit()

        # 7. Submitter cannot assign themselves via /submit-for-approval -> 400 Bad Request
        r_self_submit = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{draft_sub.id}/submit-for-approval",
            headers=h_creator,
            json={"assigned_reviewer_id": str(creator.id), "comments": "Self assigning."},
        )
        assert r_self_submit.status_code == status.HTTP_400_BAD_REQUEST
        assert "Independent review required: Submitter cannot be assigned as the reviewer." in r_self_submit.json()["detail"]

        # 8. Submitter submits with selected independent reviewer -> 200 OK & assigned_reviewer_id set
        r_valid_submit = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{draft_sub.id}/submit-for-approval",
            headers=h_creator,
            json={"assigned_reviewer_id": str(reviewer.id), "comments": "Assigned to staff reviewer."},
        )
        assert r_valid_submit.status_code == status.HTTP_200_OK
        assert r_valid_submit.json()["status"] == "PENDING_REVIEW"
        assert r_valid_submit.json()["assigned_reviewer_id"] == str(reviewer.id)

        # 9. Another draft submission submitted without reviewer (Auto-assign) -> 200 OK
        draft_sub2 = ContentSubmission(
            id=uuid.uuid4(),
            organisation_id=org.id,
            brand_kit_id=brand_kit.id,
            brand_kit_version_id=active_version.id,
            revision_number=1,
            title="Draft Test Auto Assign",
            content_text="Sample text for auto assign.",
            submitted_by_user_id=creator.id,
            status=SubmissionStatus.DRAFT,
        )
        db.add(draft_sub2)
        db.commit()

        r_auto_submit = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{draft_sub2.id}/submit-for-approval",
            headers=h_creator,
            json={"comments": "Auto assign review."},
        )
        assert r_auto_submit.status_code == status.HTTP_200_OK
        assert r_auto_submit.json()["status"] == "PENDING_REVIEW"

    app.dependency_overrides.clear()
