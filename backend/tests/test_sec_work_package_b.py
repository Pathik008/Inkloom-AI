"""Tests for Work Package B: SEC-03 (State Machine & Concurrency) and SEC-05 (Reviewer Authority)."""
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch

from app.core.security import create_access_token
from app.main import app
from app.models import (
    ContentReviewAction,
    ContentSubmission,
    OrganisationMembership,
    RoleName,
    SubmissionStatus,
    User,
)
from app.services.organisation_service import get_role_by_name
from tests.test_stage3_2_brand_kit_service_and_api import (  # noqa: F401
    _create_test_user_and_org,
    anyio_backend,
    test_db,
)


def _auth(user: User, org_id: uuid.UUID) -> dict[str, str]:
    tok, _, _ = create_access_token(subject=user.id, email=user.email)
    return {"Authorization": f"Bearer {tok}", "X-Organisation-ID": str(org_id)}


def _make_member(db, org_id: uuid.UUID, role_name: str, prefix: str = "user") -> User:
    u = User(
        id=uuid.uuid4(),
        full_name=f"{prefix.title()} Member",
        email=f"{prefix}-{uuid.uuid4().hex[:6]}@example.com",
        password_hash="hashed",
        is_active=True,
        is_verified=True,
    )
    db.add(u)
    db.flush()
    role = get_role_by_name(db, role_name)
    m = OrganisationMembership(
        id=uuid.uuid4(),
        organisation_id=org_id,
        user_id=u.id,
        role_id=role.id,
        status="ACTIVE",
    )
    db.add(m)
    db.commit()
    return u


async def _setup_test_kit(client, headers, org_id):
    r = await client.post(
        f"/api/v1/organisations/{org_id}/brand-kits",
        json={"name": "WP-B Brand Kit", "description": "Testing WP-B"},
        headers=headers,
    )
    assert r.status_code == 201
    kit_id = r.json()["id"]
    draft_id = r.json()["versions"][0]["id"]
    r2 = await client.post(
        f"/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{draft_id}/publish",
        headers=headers,
    )
    assert r2.status_code == 200
    return kit_id


@pytest.mark.anyio
async def test_sec03_legal_and_illegal_submission_transitions(test_db):
    """SEC-03: Validate that submit-for-approval only allows DRAFT and CHANGES_REQUESTED."""
    admin, org, _ = _create_test_user_and_org(test_db, suffix="sec03a", role_name=RoleName.ADMIN)
    reviewer = _make_member(test_db, org.id, RoleName.REVIEWER, prefix="rev03a")
    admin_hdr = _auth(admin, org.id)
    rev_hdr = _auth(reviewer, org.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        kit_id = await _setup_test_kit(client, admin_hdr, org.id)

        # 1. Create submission (starts in DRAFT)
        r = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions",
            json={"brand_kit_id": kit_id, "title": "Submission 1", "content_text": "Draft content"},
            headers=admin_hdr,
        )
        assert r.status_code == 201
        sub_id = r.json()["id"]
        assert r.json()["status"] == SubmissionStatus.DRAFT

        # 2. DRAFT -> PENDING_REVIEW: Allowed
        r_sub = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/submit-for-approval",
            headers=admin_hdr,
        )
        assert r_sub.status_code == 200
        assert r_sub.json()["status"] == SubmissionStatus.PENDING_REVIEW

        # 3. PENDING_REVIEW -> submit-for-approval: Disallowed (409 Conflict)
        r_sub_repeat = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/submit-for-approval",
            headers=admin_hdr,
        )
        assert r_sub_repeat.status_code == 409
        assert "Cannot submit submission in 'PENDING_REVIEW' status" in r_sub_repeat.json()["detail"]

        # 4. Request changes: PENDING_REVIEW -> CHANGES_REQUESTED
        r_changes = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/decide",
            json={"decision": "REQUEST_CHANGES", "comments": "Fix typo"},
            headers=rev_hdr,
        )
        assert r_changes.status_code == 200
        assert r_changes.json()["status"] == SubmissionStatus.CHANGES_REQUESTED

        # 5. CHANGES_REQUESTED -> PENDING_REVIEW: Allowed
        r_resub = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/submit-for-approval",
            headers=admin_hdr,
        )
        assert r_resub.status_code == 200
        assert r_resub.json()["status"] == SubmissionStatus.PENDING_REVIEW

        # 6. Approve: PENDING_REVIEW -> APPROVED
        r_app = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/decide",
            json={"decision": "APPROVE"},
            headers=rev_hdr,
        )
        assert r_app.status_code == 200
        assert r_app.json()["status"] == SubmissionStatus.APPROVED

        # 7. APPROVED -> submit-for-approval: Disallowed (409 Conflict)
        r_app_sub = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/submit-for-approval",
            headers=admin_hdr,
        )
        assert r_app_sub.status_code == 409
        assert "Cannot submit submission in 'APPROVED' status" in r_app_sub.json()["detail"]


@pytest.mark.anyio
async def test_sec03_decision_state_machine_and_terminal_states(test_db):
    """SEC-03: Decisions are only allowed from PENDING_REVIEW or UNDER_REVIEW."""
    admin, org, _ = _create_test_user_and_org(test_db, suffix="sec03b", role_name=RoleName.ADMIN)
    reviewer = _make_member(test_db, org.id, RoleName.REVIEWER, prefix="rev03b")
    admin_hdr = _auth(admin, org.id)
    rev_hdr = _auth(reviewer, org.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        kit_id = await _setup_test_kit(client, admin_hdr, org.id)

        # 1. DRAFT cannot be decided directly
        r = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions",
            json={"brand_kit_id": kit_id, "title": "Submission DRAFT", "content_text": "Draft content"},
            headers=admin_hdr,
        )
        sub_id = r.json()["id"]

        r_decide_draft = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/decide",
            json={"decision": "APPROVE"},
            headers=rev_hdr,
        )
        assert r_decide_draft.status_code == 409
        assert "Cannot decide approval on submission in 'DRAFT' status" in r_decide_draft.json()["detail"]

        # 2. Reject workflow: DRAFT -> PENDING_REVIEW -> REJECTED
        await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/submit-for-approval",
            headers=admin_hdr,
        )
        r_reject = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/decide",
            json={"decision": "REJECT", "comments": "Violates core policy"},
            headers=rev_hdr,
        )
        assert r_reject.status_code == 200
        assert r_reject.json()["status"] == SubmissionStatus.REJECTED

        # 3. REJECTED is terminal: cannot decide again or submit
        r_redecide = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/decide",
            json={"decision": "APPROVE"},
            headers=rev_hdr,
        )
        assert r_redecide.status_code == 409
        assert "Cannot decide approval on submission in 'REJECTED' status" in r_redecide.json()["detail"]

        r_resub_rej = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/submit-for-approval",
            headers=admin_hdr,
        )
        assert r_resub_rej.status_code == 409

        # 4. Cannot assign reviewer to terminal REJECTED submission
        r_assign_rej = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/assign-reviewer",
            json={"reviewer_id": str(reviewer.id)},
            headers=admin_hdr,
        )
        assert r_assign_rej.status_code == 409


@pytest.mark.anyio
async def test_sec03_atomic_decision_rollback(test_db):
    """SEC-03: If an error occurs in decide_approval, status and review actions roll back atomically."""
    from app.services import compliance_service

    admin, org, _ = _create_test_user_and_org(test_db, suffix="sec03c", role_name=RoleName.ADMIN)
    reviewer = _make_member(test_db, org.id, RoleName.REVIEWER, prefix="rev03c")
    admin_hdr = _auth(admin, org.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        kit_id = await _setup_test_kit(client, admin_hdr, org.id)

        r = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions",
            json={"brand_kit_id": kit_id, "title": "Rollback Test", "content_text": "Safe text"},
            headers=admin_hdr,
        )
        sub_id = uuid.UUID(r.json()["id"])
        await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/submit-for-approval",
            headers=admin_hdr,
        )

    # Initial actions count
    actions_count_before = len(test_db.query(ContentReviewAction).filter_by(submission_id=sub_id).all())

    # Simulate an error during db.commit() inside decide_approval
    with patch.object(test_db, "commit", side_effect=RuntimeError("Simulated DB commit error")):
        with pytest.raises(RuntimeError, match="Simulated DB commit error"):
            compliance_service.decide_approval(
                test_db,
                organisation_id=org.id,
                user_id=reviewer.id,
                submission_id=sub_id,
                decision="APPROVE",
            )

    # Verify atomic rollback
    sub = test_db.query(ContentSubmission).filter_by(id=sub_id).one()
    assert sub.status == SubmissionStatus.PENDING_REVIEW  # Not updated to APPROVED
    assert sub.reviewed_by_user_id is None
    actions_count_after = len(test_db.query(ContentReviewAction).filter_by(submission_id=sub_id).all())
    assert actions_count_after == actions_count_before  # No orphaned APPROVE action persisted


@pytest.mark.anyio
async def test_sec05_reviewer_eligibility_and_filtering(test_db):
    """SEC-05: list_eligible_reviewers returns ONLY active ADMIN and REVIEWER members."""
    admin, org, _ = _create_test_user_and_org(test_db, suffix="sec05a", role_name=RoleName.ADMIN)
    rev = _make_member(test_db, org.id, RoleName.REVIEWER, prefix="rev")
    bm = _make_member(test_db, org.id, RoleName.BRAND_MANAGER, prefix="bm")
    cc = _make_member(test_db, org.id, RoleName.CONTENT_CREATOR, prefix="cc")
    admin_hdr = _auth(admin, org.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/organisations/{org.id}/compliance/reviewers",
            headers=admin_hdr,
        )
        assert resp.status_code == 200
        eligible = resp.json()
        eligible_ids = {u["id"] for u in eligible}
        eligible_roles = {u["role"] for u in eligible}

        assert str(admin.id) in eligible_ids
        assert str(rev.id) in eligible_ids
        assert str(bm.id) not in eligible_ids
        assert str(cc.id) not in eligible_ids
        assert eligible_roles.issubset({RoleName.ADMIN, RoleName.REVIEWER})


@pytest.mark.anyio
async def test_sec05_reviewer_assignment_permissions_and_rbac(test_db):
    """SEC-05: assign_reviewer allows only ADMIN/REVIEWER; rejects BRAND_MANAGER/CONTENT_CREATOR."""
    admin, org, _ = _create_test_user_and_org(test_db, suffix="sec05b", role_name=RoleName.ADMIN)
    rev = _make_member(test_db, org.id, RoleName.REVIEWER, prefix="rev")
    bm = _make_member(test_db, org.id, RoleName.BRAND_MANAGER, prefix="bm")
    cc = _make_member(test_db, org.id, RoleName.CONTENT_CREATOR, prefix="cc")
    admin_hdr = _auth(admin, org.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        kit_id = await _setup_test_kit(client, admin_hdr, org.id)

        r = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions",
            json={"brand_kit_id": kit_id, "title": "Assignment RBAC Test", "content_text": "Content"},
            headers=admin_hdr,
        )
        sub_id = r.json()["id"]

        # 1. Assigning REVIEWER succeeds
        r_rev = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/assign-reviewer",
            json={"reviewer_id": str(rev.id)},
            headers=admin_hdr,
        )
        assert r_rev.status_code == 200
        assert r_rev.json()["assigned_reviewer_id"] == str(rev.id)

        # 2. Assigning ADMIN succeeds
        r_adm = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/assign-reviewer",
            json={"reviewer_id": str(admin.id)},
            headers=admin_hdr,
        )
        assert r_adm.status_code == 200
        assert r_adm.json()["assigned_reviewer_id"] == str(admin.id)

        # 3. Assigning BRAND_MANAGER fails with 400 Bad Request
        r_bm = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/assign-reviewer",
            json={"reviewer_id": str(bm.id)},
            headers=admin_hdr,
        )
        assert r_bm.status_code == 400
        assert "Target reviewer does not hold approval authority" in r_bm.json()["detail"]

        # 4. Assigning CONTENT_CREATOR fails with 400 Bad Request
        r_cc = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/assign-reviewer",
            json={"reviewer_id": str(cc.id)},
            headers=admin_hdr,
        )
        assert r_cc.status_code == 400
        assert "Target reviewer does not hold approval authority" in r_cc.json()["detail"]

        # 5. Assigning non-existent user returns 404 Not Found
        r_non = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/assign-reviewer",
            json={"reviewer_id": str(uuid.uuid4())},
            headers=admin_hdr,
        )
        assert r_non.status_code == 404
        assert "Target reviewer is not an active member" in r_non.json()["detail"]

        # 6. submit_for_approval with assigned_reviewer_id enforces same role validation on fresh draft
        r_draft2 = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions",
            json={"brand_kit_id": kit_id, "title": "Submit Assignment Test", "content_text": "Draft content"},
            headers=admin_hdr,
        )
        draft2_id = r_draft2.json()["id"]

        r_sub_bm = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{draft2_id}/submit-for-approval",
            json={"assigned_reviewer_id": str(bm.id)},
            headers=admin_hdr,
        )
        assert r_sub_bm.status_code == 400
        assert "Target reviewer does not hold approval authority" in r_sub_bm.json()["detail"]

        r_sub_rev = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{draft2_id}/submit-for-approval",
            json={"assigned_reviewer_id": str(rev.id)},
            headers=admin_hdr,
        )
        assert r_sub_rev.status_code == 200
        assert r_sub_rev.json()["assigned_reviewer_id"] == str(rev.id)


@pytest.mark.anyio
async def test_cr02_cannot_assign_reviewer_to_terminal_submission(test_db):
    """CR-02: Prevent reviewer assignment to APPROVED or REJECTED terminal submissions."""
    from fastapi import HTTPException
    from app.services import compliance_service

    admin, org, _ = _create_test_user_and_org(test_db, suffix="cr02a", role_name=RoleName.ADMIN)
    rev = _make_member(test_db, org.id, RoleName.REVIEWER, prefix="cr02rev")
    admin_hdr = _auth(admin, org.id)
    rev_hdr = _auth(rev, org.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        kit_id = await _setup_test_kit(client, admin_hdr, org.id)

        # 1. Approved submission terminal check
        r1 = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions",
            json={"brand_kit_id": kit_id, "title": "Approved Sub", "content_text": "Approved content"},
            headers=admin_hdr,
        )
        sub1_id = r1.json()["id"]
        await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub1_id}/submit-for-approval",
            headers=admin_hdr,
        )
        await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub1_id}/decide",
            json={"decision": "APPROVE"},
            headers=rev_hdr,
        )

        r_assign_app = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub1_id}/assign-reviewer",
            json={"reviewer_id": str(rev.id)},
            headers=admin_hdr,
        )
        assert r_assign_app.status_code == 409
        assert "Cannot assign reviewer to submission in 'APPROVED' status" in r_assign_app.json()["detail"]

        # 2. Rejected submission terminal check
        r2 = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions",
            json={"brand_kit_id": kit_id, "title": "Rejected Sub", "content_text": "Rejected content"},
            headers=admin_hdr,
        )
        sub2_id = r2.json()["id"]
        await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub2_id}/submit-for-approval",
            headers=admin_hdr,
        )
        await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub2_id}/decide",
            json={"decision": "REJECT", "comments": "Failed"},
            headers=rev_hdr,
        )

        r_assign_rej = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub2_id}/assign-reviewer",
            json={"reviewer_id": str(rev.id)},
            headers=admin_hdr,
        )
        assert r_assign_rej.status_code == 409
        assert "Cannot assign reviewer to submission in 'REJECTED' status" in r_assign_rej.json()["detail"]

        # 3. Post-lock state re-validation: verify assign_reviewer uses for_update=True and checks status
        sub1_uuid = uuid.UUID(sub1_id)
        with pytest.raises(HTTPException) as exc_info:
            compliance_service.assign_reviewer(
                test_db,
                organisation_id=org.id,
                user_id=admin.id,
                submission_id=sub1_uuid,
                reviewer_id=rev.id,
            )
        assert exc_info.value.status_code == 409
        assert "Cannot assign reviewer to submission in 'APPROVED' status" in exc_info.value.detail
