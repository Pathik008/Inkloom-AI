"""Comprehensive Stage 3.2 Automated Test Suite: Brand Kit Service, API, Immutability & RBAC.

Covers:
1. Brand Kit CRUD operations.
2. Sequential DRAFT version creation, deep-copy cloning, and single-draft constraint.
3. Version publication with quality gates, automatic archival supersession, and active version binding.
4. Version archival and active version unbinding.
5. Set active version validation (same-tenant, same-kit, PUBLISHED only).
6. Cross-tenant and cross-kit isolation (IDOR protection).
7. RBAC permission enforcement (ADMIN, BRAND_MANAGER, CONTENT_CREATOR, REVIEWER).
8. Immutability protection for published and archived versions.
"""
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import auth_rate_limiter, create_access_token
from app.database import Base, get_db
from app.main import app
from app.models import (
    ApprovedBrandFact,
    BrandIdentity,
    BrandKit,
    BrandKitVersion,
    BrandKitVersionStatus,
    ComplianceRule,
    FactCategory,
    FactRuleApprovalStatus,
    Organisation,
    OrganisationMembership,
    RoleName,
    User,
)
from app.schemas import (
    BrandIdentityCreateRequest,
    BrandIdentityUpdateRequest,
    BrandKitCreateRequest,
    BrandKitUpdateRequest,
    BrandKitVersionCreateRequest,
    BrandKitVersionUpdateRequest,
    SetActiveVersionRequest,
)
from app.services import brand_kit_service
from app.services.rbac_service import seed_roles_and_permissions


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def test_db() -> Session:
    """Isolated in-memory SQLite database session with foreign keys and seeded RBAC."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    seed_roles_and_permissions(session)
    auth_rate_limiter.reset()

    def _override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield session
    finally:
        app.dependency_overrides.clear()
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _create_test_user_and_org(
    db: Session,
    suffix: str = "1",
    role_name: str = RoleName.ADMIN,
) -> tuple[User, Organisation, str]:
    """Helper creating user, organisation, membership with specified role, and access token."""
    user = User(
        id=uuid.uuid4(),
        full_name=f"User {suffix}",
        email=f"user_{suffix}@example.com",
        password_hash="argon2_test_hash",
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    db.flush()

    org = Organisation(
        id=uuid.uuid4(),
        name=f"Enterprise {suffix}",
        slug=f"enterprise-{suffix}-{uuid.uuid4().hex[:6]}",
        created_by=user.id,
    )
    db.add(org)
    db.flush()

    from app.services.organisation_service import get_role_by_name
    role = get_role_by_name(db, role_name)

    membership = OrganisationMembership(
        id=uuid.uuid4(),
        user_id=user.id,
        organisation_id=org.id,
        role_id=role.id,
        status="ACTIVE",
    )
    db.add(membership)
    db.commit()

    token, _, _ = create_access_token(
        subject=user.id,
        email=user.email,
    )
    return user, org, token


# ==============================================================================
# 1. Domain Service Unit Tests
# ==============================================================================


def test_service_create_brand_kit_flow(test_db: Session) -> None:
    user, org, _ = _create_test_user_and_org(test_db, "svc1")

    payload = BrandKitCreateRequest(
        name="Acme Corp Hub",
        description="Global brand kit",
        industry="Technology",
        identity=BrandIdentityCreateRequest(
            brand_name="Acme",
            tagline="Leading Innovation",
            primary_color_hex="#1A2B3C",
        ),
    )
    kit = brand_kit_service.create_brand_kit(
        test_db,
        organisation_id=org.id,
        user_id=user.id,
        payload=payload,
    )

    assert kit.id is not None
    assert kit.organisation_id == org.id
    assert kit.name == "Acme Corp Hub"
    assert kit.slug == "acme-corp-hub"
    assert kit.active_version_id is None
    assert kit.is_archived is False
    assert len(kit.versions) == 1

    v1 = kit.versions[0]
    assert v1.version_number == 1
    assert v1.status == BrandKitVersionStatus.DRAFT
    assert v1.identity is not None
    assert v1.identity.brand_name == "Acme"
    assert v1.identity.primary_color_hex == "#1A2B3C"


def test_service_single_draft_constraint_and_version_increment(test_db: Session) -> None:
    user, org, _ = _create_test_user_and_org(test_db, "svc2")

    kit = brand_kit_service.create_brand_kit(
        test_db,
        organisation_id=org.id,
        user_id=user.id,
        payload=BrandKitCreateRequest(name="Kit Multi"),
    )

    # Creating a second draft while v1 is still DRAFT must fail with 409
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        brand_kit_service.create_draft_version(
            test_db,
            organisation_id=org.id,
            user_id=user.id,
            brand_kit_id=kit.id,
        )
    assert exc_info.value.status_code == 409
    assert "already has a DRAFT version" in exc_info.value.detail

    # Publish v1
    v1 = kit.versions[0]
    brand_kit_service.publish_version(
        test_db,
        organisation_id=org.id,
        user_id=user.id,
        brand_kit_id=kit.id,
        version_id=v1.id,
    )
    test_db.refresh(kit)
    assert kit.active_version_id == v1.id
    assert v1.status == BrandKitVersionStatus.PUBLISHED

    # Now creating a new draft succeeds and creates v2
    v2 = brand_kit_service.create_draft_version(
        test_db,
        organisation_id=org.id,
        user_id=user.id,
        brand_kit_id=kit.id,
        payload=BrandKitVersionCreateRequest(changelog="Version 2 draft"),
    )
    assert v2.version_number == 2
    assert v2.status == BrandKitVersionStatus.DRAFT
    assert v2.cloned_from_version_id == v1.id
    assert v2.identity.brand_name == v1.identity.brand_name


def test_service_deep_copy_cloning_of_facts_and_rules(test_db: Session) -> None:
    user, org, _ = _create_test_user_and_org(test_db, "svc3")

    kit = brand_kit_service.create_brand_kit(
        test_db,
        organisation_id=org.id,
        user_id=user.id,
        payload=BrandKitCreateRequest(name="Cloned Kit"),
    )
    v1 = kit.versions[0]

    # Add an approved fact and rule to v1
    fact = ApprovedBrandFact(
        brand_kit_version_id=v1.id,
        organisation_id=org.id,
        category=FactCategory.PRODUCT_SPEC,
        subject_name="Cloud Platform",
        fact_key="sla.uptime",
        fact_value="99.99%",
        source_reference="Product Docs",
        approval_status=FactRuleApprovalStatus.APPROVED,
        is_active=True,
    )
    rule = ComplianceRule(
        brand_kit_version_id=v1.id,
        organisation_id=org.id,
        rule_code="DISC-001",
        rule_type="MANDATORY_DISCLAIMER",
        title="Pricing Disclaimer",
        description="Must show tax disclaimer",
        target_pattern="taxes not included",
        source_reference="Product Docs",
        approval_status=FactRuleApprovalStatus.APPROVED,
        is_active=True,
    )
    test_db.add_all([fact, rule])
    test_db.commit()

    # Publish v1
    brand_kit_service.publish_version(
        test_db,
        organisation_id=org.id,
        user_id=user.id,
        brand_kit_id=kit.id,
        version_id=v1.id,
    )

    # Clone v2
    v2 = brand_kit_service.create_draft_version(
        test_db,
        organisation_id=org.id,
        user_id=user.id,
        brand_kit_id=kit.id,
    )

    test_db.refresh(v2)
    assert len(v2.facts) == 1
    assert v2.facts[0].fact_key == "sla.uptime"
    assert v2.facts[0].id != fact.id
    assert v2.facts[0].brand_kit_version_id == v2.id

    assert len(v2.rules) == 1
    assert v2.rules[0].rule_code == "DISC-001"
    assert v2.rules[0].id != rule.id
    assert v2.rules[0].brand_kit_version_id == v2.id


def test_service_pre_publish_validation_gates(test_db: Session) -> None:
    user, org, _ = _create_test_user_and_org(test_db, "svc4")

    kit = brand_kit_service.create_brand_kit(
        test_db,
        organisation_id=org.id,
        user_id=user.id,
        payload=BrandKitCreateRequest(name="Gate Kit"),
    )
    v1 = kit.versions[0]

    # Add a PENDING_REVIEW fact
    fact = ApprovedBrandFact(
        brand_kit_version_id=v1.id,
        organisation_id=org.id,
        category=FactCategory.GENERAL,
        subject_name="Test",
        fact_key="pending.fact",
        fact_value="val",
        source_reference="doc",
        approval_status=FactRuleApprovalStatus.PENDING_REVIEW,
    )
    test_db.add(fact)
    test_db.commit()

    # Publishing must fail with 422 Unprocessable Entity
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        brand_kit_service.publish_version(
            test_db,
            organisation_id=org.id,
            user_id=user.id,
            brand_kit_id=kit.id,
            version_id=v1.id,
        )
    assert exc_info.value.status_code == 422
    assert "pending review or rejected" in exc_info.value.detail

    # Approve fact
    fact.approval_status = FactRuleApprovalStatus.APPROVED
    test_db.commit()

    # Now publishing succeeds
    pub = brand_kit_service.publish_version(
        test_db,
        organisation_id=org.id,
        user_id=user.id,
        brand_kit_id=kit.id,
        version_id=v1.id,
    )
    assert pub.status == BrandKitVersionStatus.PUBLISHED


def test_service_set_active_version_validations(test_db: Session) -> None:
    user, org_a, _ = _create_test_user_and_org(test_db, "svc5a")
    _, org_b, _ = _create_test_user_and_org(test_db, "svc5b")

    kit_a1 = brand_kit_service.create_brand_kit(
        test_db, organisation_id=org_a.id, user_id=user.id, payload=BrandKitCreateRequest(name="Kit A1")
    )
    kit_a2 = brand_kit_service.create_brand_kit(
        test_db, organisation_id=org_a.id, user_id=user.id, payload=BrandKitCreateRequest(name="Kit A2")
    )
    kit_b1 = brand_kit_service.create_brand_kit(
        test_db, organisation_id=org_b.id, user_id=user.id, payload=BrandKitCreateRequest(name="Kit B1")
    )

    v_a1_1 = kit_a1.versions[0]
    v_a2_1 = kit_a2.versions[0]
    v_b1_1 = kit_b1.versions[0]

    # Publish v_a1_1 and v_b1_1
    brand_kit_service.publish_version(test_db, organisation_id=org_a.id, user_id=user.id, brand_kit_id=kit_a1.id, version_id=v_a1_1.id)
    brand_kit_service.publish_version(test_db, organisation_id=org_b.id, user_id=user.id, brand_kit_id=kit_b1.id, version_id=v_b1_1.id)

    from fastapi import HTTPException

    # 1. Rejects non-published version (v_a2_1 is DRAFT)
    with pytest.raises(HTTPException) as exc:
        brand_kit_service.set_active_version(
            test_db, organisation_id=org_a.id, user_id=user.id, brand_kit_id=kit_a2.id, version_id=v_a2_1.id
        )
    assert exc.value.status_code == 409
    assert "Only PUBLISHED versions can be set as active" in exc.value.detail

    # 2. Rejects cross-kit version (v_a1_1 belongs to kit_a1, not kit_a2)
    with pytest.raises(HTTPException) as exc:
        brand_kit_service.set_active_version(
            test_db, organisation_id=org_a.id, user_id=user.id, brand_kit_id=kit_a2.id, version_id=v_a1_1.id
        )
    assert exc.value.status_code == 400
    assert "Selected version belongs to a different Brand Kit" in exc.value.detail

    # 3. Rejects cross-tenant version (v_b1_1 belongs to org_b, not org_a)
    with pytest.raises(HTTPException) as exc:
        brand_kit_service.set_active_version(
            test_db, organisation_id=org_a.id, user_id=user.id, brand_kit_id=kit_a1.id, version_id=v_b1_1.id
        )
    assert exc.value.status_code == 404


def test_service_archive_active_version_clears_active_pointer(test_db: Session) -> None:
    user, org, _ = _create_test_user_and_org(test_db, "svc6")
    kit = brand_kit_service.create_brand_kit(
        test_db, organisation_id=org.id, user_id=user.id, payload=BrandKitCreateRequest(name="Archive Kit")
    )
    v1 = kit.versions[0]
    brand_kit_service.publish_version(test_db, organisation_id=org.id, user_id=user.id, brand_kit_id=kit.id, version_id=v1.id)
    test_db.refresh(kit)
    assert kit.active_version_id == v1.id

    # Archive v1
    arch = brand_kit_service.archive_version(test_db, organisation_id=org.id, user_id=user.id, brand_kit_id=kit.id, version_id=v1.id)
    assert arch.status == BrandKitVersionStatus.ARCHIVED
    test_db.refresh(kit)
    assert kit.active_version_id is None


# ==============================================================================
# 2. HTTP API & REST Integration Tests
# ==============================================================================


@pytest.mark.anyio
async def test_api_brand_kit_crud_flow(test_db: Session) -> None:
    print("CRUD-1: setting up user...", flush=True)
    user, org, token = _create_test_user_and_org(test_db, "api1", RoleName.ADMIN)
    print("CRUD-2: creating transport...", flush=True)
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token}"}

    print("CRUD-3: entering async client...", flush=True)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        print("CRUD-4: sending POST brand-kits...", flush=True)
        create_resp = await client.post(
            f"/api/v1/organisations/{org.id}/brand-kits",
            headers=headers,
            json={
                "name": "Stripe Payments Kit",
                "description": "Primary corporate brand book",
                "industry": "FinTech",
                "identity": {
                    "brand_name": "Stripe",
                    "tagline": "Financial Infrastructure for the Internet",
                    "primary_color_hex": "#635BFF",
                },
            },
        )
        print("CRUD-5: response received:", create_resp.status_code, flush=True)
        assert create_resp.status_code == 201, create_resp.text
        body = create_resp.json()
        kit_id = body["id"]
        assert body["name"] == "Stripe Payments Kit"
        assert body["slug"] == "stripe-payments-kit"
        assert len(body["versions"]) == 1
        v1_id = body["versions"][0]["id"]

        # 2. List Brand Kits
        list_resp = await client.get(
            f"/api/v1/organisations/{org.id}/brand-kits",
            headers=headers,
        )
        assert list_resp.status_code == 200
        kits = list_resp.json()
        assert len(kits) == 1
        assert kits[0]["id"] == kit_id
        assert kits[0]["draft_version"]["id"] == v1_id

        # 3. Get Brand Kit details
        detail_resp = await client.get(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit_id}",
            headers=headers,
        )
        assert detail_resp.status_code == 200
        assert detail_resp.json()["id"] == kit_id

        # 4. Update Brand Kit container metadata
        update_resp = await client.patch(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit_id}",
            headers=headers,
            json={"description": "Updated corporate brand kit", "industry": "Banking"},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["description"] == "Updated corporate brand kit"
        assert update_resp.json()["industry"] == "Banking"


@pytest.mark.anyio
async def test_api_version_lifecycle_publish_archive_and_cloning(test_db: Session) -> None:
    user, org, token = _create_test_user_and_org(test_db, "api2", RoleName.BRAND_MANAGER)
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Create kit
        create_resp = await client.post(
            f"/api/v1/organisations/{org.id}/brand-kits",
            headers=headers,
            json={"name": "Lifecycle Kit"},
        )
        assert create_resp.status_code == 201
        kit_id = create_resp.json()["id"]
        v1_id = create_resp.json()["versions"][0]["id"]

        # Update draft v1 identity
        patch_v1 = await client.patch(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit_id}/versions/{v1_id}",
            headers=headers,
            json={
                "changelog": "Initial draft ready for publish",
                "identity": {"tagline": "Crafting the Future"},
            },
        )
        assert patch_v1.status_code == 200
        assert patch_v1.json()["identity"]["tagline"] == "Crafting the Future"

        # Publish v1
        pub_v1 = await client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit_id}/versions/{v1_id}/publish",
            headers=headers,
        )
        assert pub_v1.status_code == 200
        assert pub_v1.json()["status"] == BrandKitVersionStatus.PUBLISHED

        # Modifying v1 now fails with 409 Conflict (immutable)
        tamper_v1 = await client.patch(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit_id}/versions/{v1_id}",
            headers=headers,
            json={"changelog": "Tampered"},
        )
        assert tamper_v1.status_code == 409

        # Clone v2 DRAFT
        create_v2 = await client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit_id}/versions",
            headers=headers,
            json={"changelog": "New v2 draft"},
        )
        assert create_v2.status_code == 201
        v2_id = create_v2.json()["id"]
        assert create_v2.json()["version_number"] == 2
        assert create_v2.json()["status"] == BrandKitVersionStatus.DRAFT
        assert create_v2.json()["identity"]["tagline"] == "Crafting the Future"

        # Second draft creation attempt rejected with 409
        dup_draft = await client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit_id}/versions",
            headers=headers,
        )
        assert dup_draft.status_code == 409

        # Publish v2 -> atomically supersedes v1 to ARCHIVED and sets active_version to v2
        pub_v2 = await client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit_id}/versions/{v2_id}/publish",
            headers=headers,
        )
        assert pub_v2.status_code == 200

        # Check v1 is now ARCHIVED
        get_v1 = await client.get(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit_id}/versions/{v1_id}",
            headers=headers,
        )
        assert get_v1.json()["status"] == BrandKitVersionStatus.ARCHIVED

        # Check kit active_version is v2
        kit_check = await client.get(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit_id}",
            headers=headers,
        )
        assert kit_check.json()["active_version_id"] == v2_id


@pytest.mark.anyio
async def test_api_tenant_isolation_cross_org_probes_blocked(test_db: Session) -> None:
    user_a, org_a, token_a = _create_test_user_and_org(test_db, "api3a", RoleName.ADMIN)
    user_b, org_b, token_b = _create_test_user_and_org(test_db, "api3b", RoleName.ADMIN)

    transport = ASGITransport(app=app)
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Org A creates a Brand Kit
        create_a = await client.post(
            f"/api/v1/organisations/{org_a.id}/brand-kits",
            headers=headers_a,
            json={"name": "Org A Confidential Kit"},
        )
        assert create_a.status_code == 201
        kit_a_id = create_a.json()["id"]
        ver_a_id = create_a.json()["versions"][0]["id"]

        # 1. User B requests Org A's URL -> 403 Forbidden (not a member of Org A)
        r1 = await client.get(
            f"/api/v1/organisations/{org_a.id}/brand-kits",
            headers=headers_b,
        )
        assert r1.status_code == 403

        # 2. User B requests Org A's kit under Org B path -> 404 Not Found (no cross-tenant leakage)
        r2 = await client.get(
            f"/api/v1/organisations/{org_b.id}/brand-kits/{kit_a_id}",
            headers=headers_b,
        )
        assert r2.status_code == 404

        # 3. User B requests Org A's version under Org B path -> 404 Not Found
        r3 = await client.get(
            f"/api/v1/organisations/{org_b.id}/brand-kits/{kit_a_id}/versions/{ver_a_id}",
            headers=headers_b,
        )
        assert r3.status_code == 404

        # 4. User B attempts to publish Org A's version under Org B path -> 404 Not Found
        r4 = await client.post(
            f"/api/v1/organisations/{org_b.id}/brand-kits/{kit_a_id}/versions/{ver_a_id}/publish",
            headers=headers_b,
        )
        assert r4.status_code == 404


@pytest.mark.anyio
async def test_api_rbac_permissions_enforcement(test_db: Session) -> None:
    # Set up members for each role in Org
    user_admin, org, token_admin = _create_test_user_and_org(test_db, "rbac_admin", RoleName.ADMIN)

    from app.services.organisation_service import get_role_by_name
    def _add_member(email: str, role_name: str) -> str:
        u = User(
            id=uuid.uuid4(),
            full_name=f"Role {role_name}",
            email=email,
            password_hash="test_hash",
            is_active=True,
            is_verified=True,
        )
        test_db.add(u)
        test_db.flush()
        m = OrganisationMembership(
            id=uuid.uuid4(),
            user_id=u.id,
            organisation_id=org.id,
            role_id=get_role_by_name(test_db, role_name).id,
            status="ACTIVE",
        )
        test_db.add(m)
        test_db.commit()
        t, _, _ = create_access_token(subject=u.id, email=u.email)
        return t

    token_bm = _add_member("bm@example.com", RoleName.BRAND_MANAGER)
    token_creator = _add_member("creator@example.com", RoleName.CONTENT_CREATOR)
    token_reviewer = _add_member("reviewer@example.com", RoleName.REVIEWER)

    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Admin creates kit (201)
        res_admin = await client.post(
            f"/api/v1/organisations/{org.id}/brand-kits",
            headers={"Authorization": f"Bearer {token_admin}"},
            json={"name": "Admin Kit"},
        )
        assert res_admin.status_code == 201
        kit_id = res_admin.json()["id"]

        # Brand Manager can also create kit (201)
        res_bm = await client.post(
            f"/api/v1/organisations/{org.id}/brand-kits",
            headers={"Authorization": f"Bearer {token_bm}"},
            json={"name": "BM Kit"},
        )
        assert res_bm.status_code == 201

        # Content Creator can READ kits (200)
        res_cc_read = await client.get(
            f"/api/v1/organisations/{org.id}/brand-kits",
            headers={"Authorization": f"Bearer {token_creator}"},
        )
        assert res_cc_read.status_code == 200

        # Content Creator CANNOT create kits (403 Forbidden)
        res_cc_create = await client.post(
            f"/api/v1/organisations/{org.id}/brand-kits",
            headers={"Authorization": f"Bearer {token_creator}"},
            json={"name": "Creator Kit"},
        )
        assert res_cc_create.status_code == 403

        # Reviewer can READ kits (200)
        res_rev_read = await client.get(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit_id}",
            headers={"Authorization": f"Bearer {token_reviewer}"},
        )
        assert res_rev_read.status_code == 200

        # Reviewer CANNOT update kits (403 Forbidden)
        res_rev_patch = await client.patch(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit_id}",
            headers={"Authorization": f"Bearer {token_reviewer}"},
            json={"name": "Tampered by Reviewer"},
        )
        assert res_rev_patch.status_code == 403
