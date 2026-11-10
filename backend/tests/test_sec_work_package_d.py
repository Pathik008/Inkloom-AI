"""Tests for Work Package D: SEC-07 (Dashboard Database Aggregation) and SEC-09 (Submitter Identity in Search & Summary)."""
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security import create_access_token
from app.main import app
from app.models import (
    BrandKit,
    BrandKitVersion,
    BrandKitVersionStatus,
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


def _create_kit_and_version(db, org_id: uuid.UUID, user_id: uuid.UUID) -> tuple[BrandKit, BrandKitVersion]:
    kit = BrandKit(
        id=uuid.uuid4(),
        organisation_id=org_id,
        name=f"Kit-{uuid.uuid4().hex[:6]}",
        slug=f"slug-{uuid.uuid4().hex[:6]}",
        created_by_user_id=user_id,
    )
    db.add(kit)
    db.flush()

    ver = BrandKitVersion(
        id=uuid.uuid4(),
        brand_kit_id=kit.id,
        organisation_id=org_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user_id,
    )
    db.add(ver)
    db.flush()

    ver.status = BrandKitVersionStatus.PUBLISHED
    ver.published_by_user_id = user_id
    kit.active_version_id = ver.id
    db.commit()
    return kit, ver


@pytest.mark.anyio
async def test_sec07_empty_organisation_metrics_returns_zero(test_db):
    """SEC-07: Organisations with 0 submissions return accurate zeros via SQL aggregation."""
    admin, org, _ = _create_test_user_and_org(test_db, suffix="sec07a", role_name=RoleName.ADMIN)
    headers = _auth(admin, org.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/organisations/{org.id}/compliance/metrics",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["organisation_id"] == str(org.id)
        assert data["total_submissions"] == 0
        assert data["pending_submissions"] == 0
        assert data["approved_submissions"] == 0
        assert data["rejected_submissions"] == 0
        assert data["changes_requested_submissions"] == 0
        assert data["draft_submissions"] == 0
        assert data["total"] == 0
        assert data["pending_review"] == 0


@pytest.mark.anyio
async def test_sec07_all_submission_statuses_aggregated_accurately(test_db):
    """SEC-07: Status counts properly aggregate DRAFT, PENDING_REVIEW, UNDER_REVIEW, APPROVED, REJECTED, CHANGES_REQUESTED."""
    admin, org, _ = _create_test_user_and_org(test_db, suffix="sec07b", role_name=RoleName.ADMIN)
    headers = _auth(admin, org.id)
    kit, ver = _create_kit_and_version(test_db, org.id, admin.id)

    # Seed submissions with known statuses
    statuses = [
        SubmissionStatus.DRAFT,
        SubmissionStatus.DRAFT,
        SubmissionStatus.PENDING_REVIEW,
        SubmissionStatus.PENDING_REVIEW,
        SubmissionStatus.UNDER_REVIEW,  # Must be grouped into pending_submissions
        SubmissionStatus.APPROVED,
        SubmissionStatus.APPROVED,
        SubmissionStatus.APPROVED,
        SubmissionStatus.REJECTED,
        SubmissionStatus.CHANGES_REQUESTED,
        SubmissionStatus.CHANGES_REQUESTED,
    ]

    for i, st in enumerate(statuses):
        sub = ContentSubmission(
            id=uuid.uuid4(),
            organisation_id=org.id,
            brand_kit_id=kit.id,
            brand_kit_version_id=ver.id,
            submitted_by_user_id=admin.id,
            revision_number=1,
            title=f"Sample {i} {st}",
            content_text="Sample text",
            status=st,
        )
        test_db.add(sub)
    test_db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/v1/organisations/{org.id}/compliance/metrics",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["total_submissions"] == len(statuses)  # 11
        assert data["draft_submissions"] == 2
        assert data["pending_submissions"] == 3  # 2 PENDING_REVIEW + 1 UNDER_REVIEW
        assert data["approved_submissions"] == 3
        assert data["rejected_submissions"] == 1
        assert data["changes_requested_submissions"] == 2

        # Verify aliases
        assert data["total"] == 11
        assert data["pending_review"] == 3
        assert data["approved"] == 3
        assert data["rejected"] == 1
        assert data["changes_requested"] == 2
        assert data["draft"] == 2


@pytest.mark.anyio
async def test_sec07_metrics_uncapped_with_over_200_submissions(test_db):
    """SEC-07: Metrics endpoint provides full database count (e.g. 215) independent of the 200 submission-list cap."""
    admin, org, _ = _create_test_user_and_org(test_db, suffix="sec07c", role_name=RoleName.ADMIN)
    headers = _auth(admin, org.id)
    kit, ver = _create_kit_and_version(test_db, org.id, admin.id)

    # Bulk insert 215 submissions (150 approved, 65 pending)
    subs = []
    for i in range(215):
        st = SubmissionStatus.APPROVED if i < 150 else SubmissionStatus.PENDING_REVIEW
        subs.append(
            ContentSubmission(
                id=uuid.uuid4(),
                organisation_id=org.id,
                brand_kit_id=kit.id,
                brand_kit_version_id=ver.id,
                submitted_by_user_id=admin.id,
                revision_number=1,
                title=f"Bulk Sub {i}",
                content_text="Bulk content",
                status=st,
            )
        )
    test_db.add_all(subs)
    test_db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Metrics endpoint returns true aggregate total (215)
        resp_metrics = await client.get(
            f"/api/v1/organisations/{org.id}/compliance/metrics",
            headers=headers,
        )
        assert resp_metrics.status_code == 200
        data = resp_metrics.json()
        assert data["total_submissions"] == 215
        assert data["approved_submissions"] == 150
        assert data["pending_submissions"] == 65

        # 2. Submissions list endpoint remains bounded by the limit cap (max 200)
        resp_list = await client.get(
            f"/api/v1/organisations/{org.id}/compliance/submissions?limit=200",
            headers=headers,
        )
        assert resp_list.status_code == 200
        list_items = resp_list.json()
        assert len(list_items) == 200  # Capped at 200


@pytest.mark.anyio
async def test_sec07_tenant_isolation_cross_org_leakage_prevented(test_db):
    """SEC-07: Metrics are strictly tenant-isolated and cross-tenant access is rejected."""
    admin_a, org_a, _ = _create_test_user_and_org(test_db, suffix="sec07d1", role_name=RoleName.ADMIN)
    admin_b, org_b, _ = _create_test_user_and_org(test_db, suffix="sec07d2", role_name=RoleName.ADMIN)
    hdr_a = _auth(admin_a, org_a.id)
    hdr_b = _auth(admin_b, org_b.id)

    kit_a, ver_a = _create_kit_and_version(test_db, org_a.id, admin_a.id)
    kit_b, ver_b = _create_kit_and_version(test_db, org_b.id, admin_b.id)

    # 4 submissions in Org A
    for i in range(4):
        test_db.add(
            ContentSubmission(
                id=uuid.uuid4(),
                organisation_id=org_a.id,
                brand_kit_id=kit_a.id,
                brand_kit_version_id=ver_a.id,
                submitted_by_user_id=admin_a.id,
                revision_number=1,
                title=f"Org A Sub {i}",
                content_text="A",
                status=SubmissionStatus.APPROVED,
            )
        )
    # 7 submissions in Org B
    for i in range(7):
        test_db.add(
            ContentSubmission(
                id=uuid.uuid4(),
                organisation_id=org_b.id,
                brand_kit_id=kit_b.id,
                brand_kit_version_id=ver_b.id,
                submitted_by_user_id=admin_b.id,
                revision_number=1,
                title=f"Org B Sub {i}",
                content_text="B",
                status=SubmissionStatus.PENDING_REVIEW,
            )
        )
    test_db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Org A sees only its 4 submissions
        r_a = await client.get(f"/api/v1/organisations/{org_a.id}/compliance/metrics", headers=hdr_a)
        assert r_a.status_code == 200
        assert r_a.json()["total_submissions"] == 4
        assert r_a.json()["approved_submissions"] == 4

        # Org B sees only its 7 submissions
        r_b = await client.get(f"/api/v1/organisations/{org_b.id}/compliance/metrics", headers=hdr_b)
        assert r_b.status_code == 200
        assert r_b.json()["total_submissions"] == 7
        assert r_b.json()["pending_submissions"] == 7

        # Cross-tenant request: Admin A requesting Org B metrics -> 403 Forbidden
        r_cross = await client.get(
            f"/api/v1/organisations/{org_b.id}/compliance/metrics",
            headers={"Authorization": hdr_a["Authorization"], "X-Organisation-ID": str(org_b.id)},
        )
        assert r_cross.status_code == 403


@pytest.mark.anyio
async def test_sec09_submission_summary_submitter_identity_and_search(test_db):
    """SEC-09: Submissions summary returns submitted_by_user_id & submitted_by_name distinct from reviewer."""
    admin, org, _ = _create_test_user_and_org(test_db, suffix="sec09a", role_name=RoleName.ADMIN)
    creator = _make_member(test_db, org.id, RoleName.CONTENT_CREATOR, prefix="alicecreator")
    reviewer = _make_member(test_db, org.id, RoleName.REVIEWER, prefix="bobreviewer")

    admin_hdr = _auth(admin, org.id)
    creator_hdr = _auth(creator, org.id)
    rev_hdr = _auth(reviewer, org.id)

    kit, ver = _create_kit_and_version(test_db, org.id, admin.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Creator creates submission
        r_create = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions",
            json={"brand_kit_id": str(kit.id), "title": "Spring Campaign Copy", "content_text": "Marketing text"},
            headers=creator_hdr,
        )
        assert r_create.status_code == 201
        sub_id = r_create.json()["id"]

        # 2. Creator submits for approval and assigns reviewer
        await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/submit-for-approval",
            json={"assigned_reviewer_id": str(reviewer.id)},
            headers=creator_hdr,
        )

        # 3. Reviewer approves submission
        await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions/{sub_id}/decide",
            json={"decision": "APPROVE", "comments": "Looks great!"},
            headers=rev_hdr,
        )

        # 4. List submissions and inspect summary payload
        r_list = await client.get(
            f"/api/v1/organisations/{org.id}/compliance/submissions",
            headers=admin_hdr,
        )
        assert r_list.status_code == 200
        items = r_list.json()
        assert len(items) == 1
        summary = items[0]

        # Verify SEC-09 submitter identity fields
        assert summary["submitted_by_user_id"] == str(creator.id)
        assert summary["submitted_by_name"] == creator.full_name
        assert "Alicecreator" in summary["submitted_by_name"]

        # Verify reviewer identity is distinct and preserved
        assert summary["assigned_reviewer_id"] == str(reviewer.id)
        assert summary["assigned_reviewer_name"] == reviewer.full_name
        assert summary["reviewed_by_name"] == reviewer.full_name
        assert "Bobreviewer" in summary["reviewed_by_name"]

        # Ensure submitter name is NOT the reviewer
        assert summary["submitted_by_name"] != summary["reviewed_by_name"]


@pytest.mark.anyio
async def test_sec09_payload_tampering_rejected(test_db):
    """SEC-09: Users cannot tamper with submitted_by_user_id or submitted_by_name via request body."""
    admin, org, _ = _create_test_user_and_org(test_db, suffix="sec09b", role_name=RoleName.ADMIN)
    creator = _make_member(test_db, org.id, RoleName.CONTENT_CREATOR, prefix="tamper")
    creator_hdr = _auth(creator, org.id)
    kit, _ = _create_kit_and_version(test_db, org.id, admin.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Attempt to forge submitted_by_user_id or submitted_by_name in payload
        r = await client.post(
            f"/api/v1/organisations/{org.id}/compliance/submissions",
            json={
                "brand_kit_id": str(kit.id),
                "title": "Tampered Submission",
                "content_text": "Text",
                "submitted_by_user_id": str(uuid.uuid4()),
                "submitted_by_name": "Forged User",
            },
            headers=creator_hdr,
        )
        # Extra fields are forbidden by Pydantic schema validation (422)
        assert r.status_code == 422
