"""Stage 4.2 tests: Human approval workflow, reviewer assignment, decision audit trail,
revision lineage, status filtering, and RBAC enforcement.
"""
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token
from app.main import app
from app.models import (
    BrandAuditLog,
    ContentReviewAction,
    ContentSubmission,
    OrganisationMembership,
    RoleName,
    SubmissionStatus,
    User,
)
from app.services.organisation_service import get_role_by_name
from tests.test_stage3_2_brand_kit_service_and_api import (  # noqa: F401  (fixtures)
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


async def _setup_published_kit(client, headers, org_id):
    # 1. Create Brand Kit
    r = await client.post(
        f"/api/v1/organisations/{org_id}/brand-kits",
        json={"name": "Approval Test Kit", "description": "Kit for approvals testing."},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    kit_id = r.json()["id"]
    draft_id = r.json()["versions"][0]["id"]

    # 2. Add Rule & Approve
    r2 = await client.post(
        f"/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{draft_id}/rules",
        json={
            "rule_type": "PROHIBITED_TERM",
            "title": "No Guaranteed Returns",
            "description": "Securities regulation.",
            "target_pattern": "guaranteed returns",
            "severity": "CRITICAL",
            "suggested_replacement": "potential returns",
        },
        headers=headers,
    )
    assert r2.status_code == 201
    rule_id = r2.json()["id"]

    r3 = await client.post(
        f"/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{draft_id}/rules/{rule_id}/approve",
        headers=headers,
    )
    assert r3.status_code == 200

    # 3. Publish Version
    r4 = await client.post(
        f"/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{draft_id}/publish",
        headers=headers,
    )
    assert r4.status_code == 200
    return kit_id


@pytest.mark.anyio
async def test_submit_for_approval_lifecycle(test_db):
    user, org, _ = _create_test_user_and_org(test_db, suffix="sub1", role_name=RoleName.ADMIN)
    headers = _auth(user, org.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        kit_id = await _setup_published_kit(client, headers, org.id)

        # 1. Submit content draft
        r = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions",
            json={
                "brand_kit_id": kit_id,
                "title": "Q4 Wealth Launch",
                "content_text": "Our fund delivers guaranteed returns for every client.",
            },
            headers=headers,
        )
        assert r.status_code == 201
        sub_id = r.json()["id"]
        assert r.json()["status"] == SubmissionStatus.DRAFT

        # 2. Submit for approval
        r_sub = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/submit-for-approval",
            json={"comments": "Please review this launch copy."},
            headers=headers,
        )
        assert r_sub.status_code == 200
        data = r_sub.json()
        assert data["status"] == SubmissionStatus.PENDING_REVIEW
        assert len(data["review_history"]) == 1
        assert data["review_history"][0]["action"] == "SUBMIT_FOR_APPROVAL"
        assert data["review_history"][0]["comments"] == "Please review this launch copy."

        # 3. Verify audit log entry
        audits = test_db.query(BrandAuditLog).filter_by(resource_id=uuid.UUID(sub_id)).all()
        assert any(a.action == "CONTENT_SUBMITTED_FOR_APPROVAL" for a in audits)


@pytest.mark.anyio
async def test_assign_reviewer_and_list_eligible_reviewers(test_db):
    admin, org, _ = _create_test_user_and_org(test_db, suffix="adm1", role_name=RoleName.ADMIN)
    reviewer = _make_member(test_db, org.id, RoleName.REVIEWER, prefix="reviewer")
    headers = _auth(admin, org.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        kit_id = await _setup_published_kit(client, headers, org.id)

        # List eligible reviewers
        r_revs = await client.get(f"/api/v1/organisations/{org.id}/compliance/reviewers", headers=headers)
        assert r_revs.status_code == 200
        rev_ids = [r["id"] for r in r_revs.json()]
        assert str(reviewer.id) in rev_ids

        # Create submission
        r = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions",
            json={
                "brand_kit_id": kit_id,
                "title": "Review Assignment Test",
                "content_text": "Safe content text here.",
            },
            headers=headers,
        )
        sub_id = r.json()["id"]

        # Assign reviewer
        r_assign = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/assign-reviewer",
            json={"reviewer_id": str(reviewer.id)},
            headers=headers,
        )
        assert r_assign.status_code == 200
        assert r_assign.json()["assigned_reviewer_id"] == str(reviewer.id)
        assert r_assign.json()["assigned_reviewer_name"] == reviewer.full_name


@pytest.mark.anyio
async def test_reviewer_approval_decisions_and_audit(test_db):
    admin, org, _ = _create_test_user_and_org(test_db, suffix="adm2", role_name=RoleName.ADMIN)
    reviewer = _make_member(test_db, org.id, RoleName.REVIEWER, prefix="auditor")
    admin_hdr = _auth(admin, org.id)
    rev_hdr = _auth(reviewer, org.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        kit_id = await _setup_published_kit(client, admin_hdr, org.id)

        # 1. Content created in DRAFT
        r = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions",
            json={"brand_kit_id": kit_id, "title": "Decision Test", "content_text": "Text for review."},
            headers=admin_hdr,
        )
        sub_id = r.json()["id"]

        # Directly deciding on DRAFT is forbidden by SEC-03 state machine (409 Conflict)
        r_draft_decide = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/decide",
            json={"decision": "APPROVE"},
            headers=rev_hdr,
        )
        assert r_draft_decide.status_code == 409

        # Submit for approval: DRAFT -> PENDING_REVIEW
        r_sub = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/submit-for-approval",
            headers=admin_hdr,
        )
        assert r_sub.status_code == 200
        assert r_sub.json()["status"] == SubmissionStatus.PENDING_REVIEW

        # 2. Reviewer requests changes
        r_req = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/decide",
            json={"decision": "REQUEST_CHANGES", "comments": "Tone is too casual."},
            headers=rev_hdr,
        )
        assert r_req.status_code == 200
        assert r_req.json()["status"] == SubmissionStatus.CHANGES_REQUESTED
        assert r_req.json()["reviewed_by_name"] == reviewer.full_name
        assert r_req.json()["reviewer_comments"] == "Tone is too casual."

        # 3. Author creates Revision 2
        r_rev2 = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/revisions",
            json={"content_text": "Updated professional text for review.", "title": "Decision Test Rev 2"},
            headers=admin_hdr,
        )
        assert r_rev2.status_code == 201
        rev2_id = r_rev2.json()["id"]
        assert r_rev2.json()["revision_number"] == 2
        assert len(r_rev2.json()["all_revisions"]) == 2

        # Revision 2 is DRAFT; submit Revision 2 for approval: DRAFT -> PENDING_REVIEW
        r_rev2_sub = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{rev2_id}/submit-for-approval",
            headers=admin_hdr,
        )
        assert r_rev2_sub.status_code == 200
        assert r_rev2_sub.json()["status"] == SubmissionStatus.PENDING_REVIEW

        # 4. Reviewer approves Revision 2
        r_app = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{rev2_id}/decide",
            json={"decision": "APPROVE", "comments": "Approved for publication."},
            headers=rev_hdr,
        )
        assert r_app.status_code == 200
        assert r_app.json()["status"] == SubmissionStatus.APPROVED


@pytest.mark.anyio
async def test_rbac_content_creator_cannot_decide_approval_403(test_db):
    admin, org, _ = _create_test_user_and_org(test_db, suffix="adm3", role_name=RoleName.ADMIN)
    creator = _make_member(test_db, org.id, RoleName.CONTENT_CREATOR, prefix="creator")
    admin_hdr = _auth(admin, org.id)
    creator_hdr = _auth(creator, org.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        kit_id = await _setup_published_kit(client, admin_hdr, org.id)

        r = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions",
            json={"brand_kit_id": kit_id, "title": "RBAC Test", "content_text": "My content draft."},
            headers=creator_hdr,
        )
        sub_id = r.json()["id"]

        # Content creator tries to self-approve -> Forbidden (403)
        r_decide = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/decide",
            json={"decision": "APPROVE", "comments": "Self approval attempt."},
            headers=creator_hdr,
        )
        assert r_decide.status_code == 403


@pytest.mark.anyio
async def test_list_submissions_status_filtering(test_db):
    admin, org, _ = _create_test_user_and_org(test_db, suffix="adm4", role_name=RoleName.ADMIN)
    headers = _auth(admin, org.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        kit_id = await _setup_published_kit(client, headers, org.id)

        # Create submission 1: DRAFT
        await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions",
            json={"brand_kit_id": kit_id, "title": "Sub 1 Draft", "content_text": "Draft content."},
            headers=headers,
        )

        # Create submission 2: Submit for approval -> PENDING_REVIEW
        r2 = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions",
            json={"brand_kit_id": kit_id, "title": "Sub 2 Pending", "content_text": "Pending content."},
            headers=headers,
        )
        sub2_id = r2.json()["id"]
        await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub2_id}/submit-for-approval",
            headers=headers,
        )

        # Filter by PENDING_REVIEW
        r_pend = await client.get(
            f"/api/v1/organisations/{org.id}/compliance/submissions?status=PENDING_REVIEW",
            headers=headers,
        )
        assert r_pend.status_code == 200
        assert all(s["status"] == SubmissionStatus.PENDING_REVIEW for s in r_pend.json())
        assert len(r_pend.json()) >= 1
