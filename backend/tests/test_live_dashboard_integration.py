"""Test suite for Phase 5.1: Live Dashboard Analytics & Telemetry Contract.

Verifies:
1. Brand Kit Summary endpoint returns live kits count.
2. Compliance Submissions list endpoint returns live submission items and states.
3. Role-based access control (RBAC) across ADMIN, BRAND_MANAGER, CONTENT_CREATOR, and REVIEWER.
4. Tenant isolation for metrics across multiple organisations.
5. Limit caps and pagination boundaries.
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
    BrandIdentity,
    BrandKit,
    BrandKitVersion,
    BrandKitVersionStatus,
    ComplianceAnalysis,
    ComplianceRule,
    ContentSubmission,
    Organisation,
    OrganisationMembership,
    Permission,
    PermissionCode,
    Role,
    RoleName,
    SubmissionStatus,
    User,
)


@pytest.fixture
def sqlite_db_session() -> Generator[Session, None, None]:
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
def seeded_tenant(sqlite_db_session: Session):
    db = sqlite_db_session
    admin_role = db.query(Role).filter(Role.name == RoleName.ADMIN).first()
    bm_role = db.query(Role).filter(Role.name == RoleName.BRAND_MANAGER).first()
    creator_role = db.query(Role).filter(Role.name == RoleName.CONTENT_CREATOR).first()
    reviewer_role = db.query(Role).filter(Role.name == RoleName.REVIEWER).first()

    user_admin = User(
        email=f"admin-{uuid.uuid4().hex[:6]}@inkloom.ai",
        full_name="Admin User",
        password_hash=hash_password("Password123!"),
        is_active=True,
        is_verified=True,
    )
    user_bm = User(
        email=f"bm-{uuid.uuid4().hex[:6]}@inkloom.ai",
        full_name="Brand Manager User",
        password_hash=hash_password("Password123!"),
        is_active=True,
        is_verified=True,
    )
    user_creator = User(
        email=f"creator-{uuid.uuid4().hex[:6]}@inkloom.ai",
        full_name="Creator User",
        password_hash=hash_password("Password123!"),
        is_active=True,
        is_verified=True,
    )
    user_reviewer = User(
        email=f"reviewer-{uuid.uuid4().hex[:6]}@inkloom.ai",
        full_name="Reviewer User",
        password_hash=hash_password("Password123!"),
        is_active=True,
        is_verified=True,
    )
    db.add_all([user_admin, user_bm, user_creator, user_reviewer])
    db.flush()

    org = Organisation(
        name="Inkloom Test Org",
        slug=f"inkloom-test-{uuid.uuid4().hex[:6]}",
        created_by=user_admin.id,
    )
    db.add(org)
    db.flush()

    m_admin = OrganisationMembership(
        user_id=user_admin.id,
        organisation_id=org.id,
        role_id=admin_role.id,
        status="ACTIVE",
    )
    m_bm = OrganisationMembership(
        user_id=user_bm.id,
        organisation_id=org.id,
        role_id=bm_role.id,
        status="ACTIVE",
    )
    m_creator = OrganisationMembership(
        user_id=user_creator.id,
        organisation_id=org.id,
        role_id=creator_role.id,
        status="ACTIVE",
    )
    m_reviewer = OrganisationMembership(
        user_id=user_reviewer.id,
        organisation_id=org.id,
        role_id=reviewer_role.id,
        status="ACTIVE",
    )
    db.add_all([m_admin, m_bm, m_creator, m_reviewer])

    # Create active Brand Kit with published version
    kit = BrandKit(
        organisation_id=org.id,
        name="Flagship Brand",
        slug="flagship-brand",
        created_by_user_id=user_admin.id,
    )
    db.add(kit)
    db.flush()

    version = BrandKitVersion(
        brand_kit_id=kit.id,
        organisation_id=org.id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user_admin.id,
    )
    db.add(version)
    db.flush()

    # Transition to PUBLISHED as required by immutability listener
    version.status = BrandKitVersionStatus.PUBLISHED
    version.published_by_user_id = user_admin.id
    kit.active_version_id = version.id
    db.flush()

    # Create submissions with distinct statuses
    # 1. Approved submission
    s1 = ContentSubmission(
        organisation_id=org.id,
        brand_kit_id=kit.id,
        brand_kit_version_id=version.id,
        submitted_by_user_id=user_admin.id,
        title="Q4 Campaign Copy",
        content_text="Approved marketing copy with zero violations.",
        status=SubmissionStatus.APPROVED,
    )
    # 2. Pending review submission
    s2 = ContentSubmission(
        organisation_id=org.id,
        brand_kit_id=kit.id,
        brand_kit_version_id=version.id,
        submitted_by_user_id=user_admin.id,
        title="Social Media Launch",
        content_text="Pending copy requiring human approval.",
        status=SubmissionStatus.PENDING_REVIEW,
    )
    # 3. Draft submission
    s3 = ContentSubmission(
        organisation_id=org.id,
        brand_kit_id=kit.id,
        brand_kit_version_id=version.id,
        submitted_by_user_id=user_admin.id,
        title="Early Draft",
        content_text="Early draft content.",
        status=SubmissionStatus.DRAFT,
    )
    db.add_all([s1, s2, s3])
    db.commit()

    return {
        "org": org,
        "admin": user_admin,
        "bm": user_bm,
        "creator": user_creator,
        "reviewer": user_reviewer,
        "kit": kit,
        "version": version,
    }


@pytest.mark.anyio
async def test_live_dashboard_api_contracts_and_metrics(sqlite_db_session: Session, seeded_tenant: dict):
    """Test that the endpoints used by DashboardHome return exact data for computing live metrics."""
    data = seeded_tenant
    org = data["org"]
    admin = data["admin"]

    def override_get_db():
        try:
            yield sqlite_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    token, _, _ = create_access_token(
        subject=str(admin.id),
        email=admin.email,
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Organisation-ID": str(org.id),
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Fetch Brand Kits
        resp_kits = await client.get(f"/api/v1/organisations/{org.id}/brand-kits", headers=headers)
        assert resp_kits.status_code == status.HTTP_200_OK
        kits_data = resp_kits.json()
        assert len(kits_data) == 1
        assert kits_data[0]["active_version_id"] is not None
        assert kits_data[0]["is_archived"] is False

        # Active brand kits metric:
        active_kits = [k for k in kits_data if not k["is_archived"] and (k.get("active_version_id") or k.get("active_version"))]
        assert len(active_kits) == 1

        # 2. Fetch Submissions
        resp_subs = await client.get(f"/api/v1/organisations/{org.id}/compliance/submissions?limit=200", headers=headers)
        assert resp_subs.status_code == status.HTTP_200_OK
        subs_data = resp_subs.json()
        assert len(subs_data) == 3

        # Compute metric aggregations
        total_submissions = len(subs_data)
        pending_reviews = len([s for s in subs_data if s["status"] in ("PENDING_REVIEW", "UNDER_REVIEW")])
        approved_content = len([s for s in subs_data if s["status"] == "APPROVED"])

        assert total_submissions == 3
        assert pending_reviews == 1
        assert approved_content == 1

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_live_dashboard_tenant_isolation(sqlite_db_session: Session, seeded_tenant: dict):
    """Verify that a second organization sees 0 metrics for its own tenant."""
    data = seeded_tenant
    admin = data["admin"]
    db = sqlite_db_session

    admin_role = db.query(Role).filter(Role.name == RoleName.ADMIN).first()

    org2 = Organisation(
        name="Second Isolated Org",
        slug=f"org2-{uuid.uuid4().hex[:6]}",
        created_by=admin.id,
    )
    db.add(org2)
    db.flush()

    m_admin2 = OrganisationMembership(
        user_id=admin.id,
        organisation_id=org2.id,
        role_id=admin_role.id,
        status="ACTIVE",
    )
    db.add(m_admin2)
    db.commit()

    def override_get_db():
        try:
            yield sqlite_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    token, _, _ = create_access_token(
        subject=str(admin.id),
        email=admin.email,
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Organisation-ID": str(org2.id),
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp_kits = await client.get(f"/api/v1/organisations/{org2.id}/brand-kits", headers=headers)
        assert resp_kits.status_code == status.HTTP_200_OK
        assert len(resp_kits.json()) == 0

        resp_subs = await client.get(f"/api/v1/organisations/{org2.id}/compliance/submissions?limit=200", headers=headers)
        assert resp_subs.status_code == status.HTTP_200_OK
        assert len(resp_subs.json()) == 0

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_live_dashboard_rbac_across_all_roles(sqlite_db_session: Session, seeded_tenant: dict):
    """Verify endpoint access and status codes across ADMIN, BRAND_MANAGER, CONTENT_CREATOR, and REVIEWER."""
    data = seeded_tenant
    org = data["org"]

    def override_get_db():
        try:
            yield sqlite_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Role 1: ADMIN (brand:read = True, content:review = True)
        tok_admin, _, _ = create_access_token(subject=str(data["admin"].id), email=data["admin"].email)
        h_admin = {"Authorization": f"Bearer {tok_admin}", "X-Organisation-ID": str(org.id)}
        r_bk = await client.get(f"/api/v1/organisations/{org.id}/brand-kits", headers=h_admin)
        r_cs = await client.get(f"/api/v1/organisations/{org.id}/compliance/submissions", headers=h_admin)
        assert r_bk.status_code == status.HTTP_200_OK
        assert r_cs.status_code == status.HTTP_200_OK

        # Role 2: BRAND_MANAGER (brand:read = True, content:review = True)
        tok_bm, _, _ = create_access_token(subject=str(data["bm"].id), email=data["bm"].email)
        h_bm = {"Authorization": f"Bearer {tok_bm}", "X-Organisation-ID": str(org.id)}
        r_bk = await client.get(f"/api/v1/organisations/{org.id}/brand-kits", headers=h_bm)
        r_cs = await client.get(f"/api/v1/organisations/{org.id}/compliance/submissions", headers=h_bm)
        assert r_bk.status_code == status.HTTP_200_OK
        assert r_cs.status_code == status.HTTP_200_OK

        # Role 3: REVIEWER (brand:read = True, content:review = True)
        tok_rev, _, _ = create_access_token(subject=str(data["reviewer"].id), email=data["reviewer"].email)
        h_rev = {"Authorization": f"Bearer {tok_rev}", "X-Organisation-ID": str(org.id)}
        r_bk = await client.get(f"/api/v1/organisations/{org.id}/brand-kits", headers=h_rev)
        r_cs = await client.get(f"/api/v1/organisations/{org.id}/compliance/submissions", headers=h_rev)
        assert r_bk.status_code == status.HTTP_200_OK
        assert r_cs.status_code == status.HTTP_200_OK

        # Role 4: CONTENT_CREATOR (brand:read = True, content:review = True)
        tok_creator, _, _ = create_access_token(subject=str(data["creator"].id), email=data["creator"].email)
        h_creator = {"Authorization": f"Bearer {tok_creator}", "X-Organisation-ID": str(org.id)}
        r_bk = await client.get(f"/api/v1/organisations/{org.id}/brand-kits", headers=h_creator)
        r_cs = await client.get(f"/api/v1/organisations/{org.id}/compliance/submissions", headers=h_creator)
        assert r_bk.status_code == status.HTTP_200_OK
        assert r_cs.status_code == status.HTTP_200_OK

    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_submissions_limit_capping(sqlite_db_session: Session, seeded_tenant: dict):
    """Verify limit parameter capping on submissions endpoint."""
    data = seeded_tenant
    org = data["org"]
    admin = data["admin"]

    def override_get_db():
        try:
            yield sqlite_db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    token, _, _ = create_access_token(subject=str(admin.id), email=admin.email)
    headers = {"Authorization": f"Bearer {token}", "X-Organisation-ID": str(org.id)}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Request with limit=1
        resp = await client.get(f"/api/v1/organisations/{org.id}/compliance/submissions?limit=1", headers=headers)
        assert resp.status_code == status.HTTP_200_OK
        assert len(resp.json()) == 1

        # Request exceeding max limit (200) triggers validation 422
        resp_over = await client.get(f"/api/v1/organisations/{org.id}/compliance/submissions?limit=500", headers=headers)
        assert resp_over.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    app.dependency_overrides.clear()
