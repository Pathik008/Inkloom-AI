"""Stage 3.1 PostgreSQL Database Models, Constraints, Triggers & Migration 0003 Test Suite.

Executes directly against live PostgreSQL 16 + pgvector to verify:
A. Migration 0003 upgrade, 9 tables, indexes, constraints, triggers, Phase 2 RBAC preservation, and vector(1024).
B. Tenant integrity (composite foreign keys & cross-tenant trigger guards).
C. Version constraints (unique version_number, single DRAFT partial index, valid status transitions).
D. Immutability (published/archived version & child lock, guideline document telemetry allowlist, append-only audit logs).
E. Downgrade to 0002 and re-upgrade to 0003 safety without losing Phase 2 permissions or data.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import os
import uuid

from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import (
    ALLOWLISTED_GUIDELINE_DOC_TELEMETRY_COLUMNS,
    ApprovedBrandFact,
    BrandAsset,
    BrandAssetType,
    BrandAuditLog,
    BrandAuditResourceType,
    BrandDocumentChunk,
    BrandGuidelineDocument,
    BrandHubImmutabilityError,
    BrandIdentity,
    BrandKit,
    BrandKitVersion,
    BrandKitVersionStatus,
    ComplianceRule,
    ComplianceRuleType,
    DocumentParsingStatus,
    FactCategory,
    FactRuleApprovalStatus,
    GuidelineDocumentCategory,
    LOCKED_GUIDELINE_DOC_COLUMNS,
    Organisation,
    Permission,
    PermissionCode,
    ProvenanceSourceType,
    ROLE_PERMISSION_MATRIX,
    Role,
    RolePermission,
    RuleMatchMode,
    RuleSeverity,
    User,
    utcnow,
)

PROJECT_ENV = Path(__file__).resolve().parents[2] / ".env"
PROJECT_ENV_VALUES = dotenv_values(PROJECT_ENV)

POSTGRES_TEST_URI = (
    os.getenv("POSTGRES_TEST_DATABASE_URL")
    or PROJECT_ENV_VALUES.get("DATABASE_URL")
)

if not POSTGRES_TEST_URI or not POSTGRES_TEST_URI.startswith(("postgresql://", "postgresql+psycopg://")):
    raise RuntimeError("Stage 3.1 database tests require a live PostgreSQL DATABASE_URL.")


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(POSTGRES_TEST_URI, pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield engine
    engine.dispose()


@pytest.fixture
def pg_tenant_fixture(pg_engine):
    """Create two isolated test organisations (Org A and Org B) and a test user on PostgreSQL, cleaning up on teardown."""
    SessionLocal = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    session = SessionLocal()

    user_id = uuid.uuid4()
    org_a_id = uuid.uuid4()
    org_b_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]

    user = User(
        id=user_id,
        full_name="Stage 3.1 Architect",
        email=f"stage31_{suffix}@example.com",
        password_hash="argon2_test_hash",
        is_active=True,
        is_verified=True,
    )
    session.add(user)
    session.flush()

    org_a = Organisation(
        id=org_a_id,
        name=f"Tenant Alpha {suffix}",
        slug=f"tenant-alpha-{suffix}",
        created_by=user_id,
    )
    org_b = Organisation(
        id=org_b_id,
        name=f"Tenant Beta {suffix}",
        slug=f"tenant-beta-{suffix}",
        created_by=user_id,
    )
    session.add_all([org_a, org_b])
    session.commit()

    try:
        yield {
            "session": session,
            "SessionLocal": SessionLocal,
            "user_id": user_id,
            "org_a_id": org_a_id,
            "org_b_id": org_b_id,
        }
    finally:
        session.rollback()
        session.close()
        with pg_engine.connect() as cleanup_conn:
            cleanup_conn.execute(
                text("DELETE FROM organisations WHERE id IN (:org_a, :org_b);"),
                {"org_a": org_a_id, "org_b": org_b_id},
            )
            cleanup_conn.execute(
                text("DELETE FROM users WHERE id = :uid;"),
                {"uid": user_id},
            )
            cleanup_conn.commit()


# ==============================================================================
# A. MIGRATION, SCHEMA, INDEXES, TRIGGERS & PHASE 2 RBAC VERIFICATION
# ==============================================================================


def test_migration_0003_tables_indexes_triggers_and_rbac(pg_engine):
    """Verify head revision 0007_content_approvals, all 9 Phase 3 tables, Phase 2 tables, partial indexes, triggers, and RBAC permissions."""
    with pg_engine.connect() as conn:
        # 1. Verify current Alembic revision
        rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
        assert rev in ("0006_compliance_workflow", "0007_content_approvals")

        # 2. Verify all 9 Phase 3 tables exist
        expected_phase3_tables = {
            "brand_kits",
            "brand_kit_versions",
            "brand_identities",
            "approved_brand_facts",
            "compliance_rules",
            "brand_assets",
            "brand_guideline_documents",
            "brand_document_chunks",
            "brand_audit_logs",
        }
        expected_phase2_tables = {
            "users",
            "organisations",
            "roles",
            "permissions",
            "role_permissions",
            "organisation_memberships",
            "organisation_invitations",
            "revoked_tokens",
        }
        existing_tables = {
            row[0]
            for row in conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
            ).fetchall()
        }
        assert expected_phase3_tables.issubset(existing_tables)
        assert expected_phase2_tables.issubset(existing_tables)

        # 3. Verify partial unique indexes uq_brand_kit_single_draft and uq_brand_kit_single_published
        idx_draft_def = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE tablename = 'brand_kit_versions' AND indexname = 'uq_brand_kit_single_draft';"
            )
        ).scalar()
        assert idx_draft_def is not None
        assert "UNIQUE INDEX" in idx_draft_def.upper()
        assert "DRAFT" in idx_draft_def

        idx_pub_def = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE tablename = 'brand_kit_versions' AND indexname = 'uq_brand_kit_single_published';"
            )
        ).scalar()
        assert idx_pub_def is not None
        assert "UNIQUE INDEX" in idx_pub_def.upper()
        assert "PUBLISHED" in idx_pub_def

        # 4. Verify all 5 PostgreSQL trigger functions exist
        expected_functions = {
            "fn_validate_brand_kit_active_version",
            "fn_enforce_brand_kit_version_immutability",
            "fn_enforce_brand_version_child_immutability",
            "fn_enforce_guideline_doc_immutability",
            "fn_validate_and_protect_brand_audit_logs",
        }
        existing_functions = {
            row[0]
            for row in conn.execute(
                text("SELECT proname FROM pg_proc WHERE proname LIKE 'fn_%';")
            ).fetchall()
        }
        assert expected_functions.issubset(existing_functions)

        # 5. Verify all 9 PostgreSQL triggers exist
        expected_triggers = {
            "trg_validate_brand_kit_active_version",
            "trg_enforce_brand_kit_version_immutability",
            "trg_enforce_brand_identities_immutability",
            "trg_enforce_approved_brand_facts_immutability",
            "trg_enforce_compliance_rules_immutability",
            "trg_enforce_brand_assets_immutability",
            "trg_enforce_brand_document_chunks_immutability",
            "trg_enforce_guideline_doc_immutability",
            "trg_validate_and_protect_brand_audit_logs",
        }
        existing_triggers = {
            row[0]
            for row in conn.execute(
                text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal;")
            ).fetchall()
        }
        assert expected_triggers.issubset(existing_triggers)

        # 6. Verify Phase 2 RBAC permissions and role mappings are intact
        for role_name, expected_codes in ROLE_PERMISSION_MATRIX.items():
            actual_codes = {
                row[0]
                for row in conn.execute(
                    text(
                        """
                        SELECT p.code
                        FROM role_permissions rp
                        JOIN roles r ON r.id = rp.role_id
                        JOIN permissions p ON p.id = rp.permission_id
                        WHERE r.name = :rname;
                        """
                    ),
                    {"rname": role_name},
                ).fetchall()
            }
            assert set(expected_codes).issubset(actual_codes), f"Missing permissions for role {role_name}"


def test_brand_document_chunks_vector_1024_and_similarity(pg_tenant_fixture):
    """Verify brand_document_chunks stores 1024-dimensional pgvector embeddings and executes cosine similarity search."""
    session = pg_tenant_fixture["session"]
    org_id = pg_tenant_fixture["org_a_id"]
    user_id = pg_tenant_fixture["user_id"]

    kit = BrandKit(
        organisation_id=org_id,
        name="Vector Test Kit",
        slug=f"vector-kit-{uuid.uuid4().hex[:6]}",
        created_by_user_id=user_id,
    )
    session.add(kit)
    session.flush()

    version = BrandKitVersion(
        brand_kit_id=kit.id,
        organisation_id=org_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user_id,
    )
    session.add(version)
    session.flush()

    doc = BrandGuidelineDocument(
        brand_kit_version_id=version.id,
        organisation_id=org_id,
        title="Vector Style Guide",
        document_category=GuidelineDocumentCategory.STYLE_GUIDE,
        original_filename="style_guide.pdf",
        stored_filename=f"{uuid.uuid4().hex}.pdf",
        storage_path=f"tenants/{org_id}/docs/style_guide.pdf",
        mime_type="application/pdf",
        file_size_bytes=4096,
        file_sha256="a" * 64,
        uploaded_by_user_id=user_id,
    )
    session.add(doc)
    session.flush()

    vec_a = [0.01] * 1024
    vec_a[0] = 0.99
    vec_b = [0.01] * 1024
    vec_b[1] = 0.99

    chunk_0 = BrandDocumentChunk(
        document_id=doc.id,
        brand_kit_version_id=version.id,
        organisation_id=org_id,
        chunk_index=0,
        page_number=1,
        section_heading="Brand Tone",
        char_start=0,
        char_end=120,
        content="Always speak with warmth and precision.",
        content_sha256="b" * 64,
        token_count=8,
        embedding=vec_a,
    )
    chunk_1 = BrandDocumentChunk(
        document_id=doc.id,
        brand_kit_version_id=version.id,
        organisation_id=org_id,
        chunk_index=1,
        page_number=2,
        section_heading="Pricing Rules",
        char_start=121,
        char_end=240,
        content="Premium Coffee MRP is â‚¹129 inclusive of taxes.",
        content_sha256="c" * 64,
        token_count=10,
        embedding=vec_b,
    )
    session.add_all([chunk_0, chunk_1])
    session.commit()

    # Query cosine distance against vec_a
    nearest_id = session.execute(
        select(BrandDocumentChunk.id)
        .where(
            BrandDocumentChunk.organisation_id == org_id,
            BrandDocumentChunk.brand_kit_version_id == version.id,
        )
        .order_by(BrandDocumentChunk.embedding.cosine_distance(vec_a))
        .limit(1)
    ).scalar_one()
    assert nearest_id == chunk_0.id


# ==============================================================================
# B. TENANT INTEGRITY & COMPOSITE FOREIGN KEY ENFORCEMENT
# ==============================================================================


def test_cross_tenant_parent_child_relationships_rejected(pg_tenant_fixture):
    """Verify PostgreSQL composite foreign keys and triggers reject all cross-organisation parent-child links."""
    session = pg_tenant_fixture["session"]
    org_a_id = pg_tenant_fixture["org_a_id"]
    org_b_id = pg_tenant_fixture["org_b_id"]
    user_id = pg_tenant_fixture["user_id"]

    # Create BrandKit and Draft Version in Org A
    kit_a = BrandKit(
        organisation_id=org_a_id,
        name="Org A Kit",
        slug=f"org-a-kit-{uuid.uuid4().hex[:6]}",
        created_by_user_id=user_id,
    )
    session.add(kit_a)
    session.flush()

    ver_a = BrandKitVersion(
        brand_kit_id=kit_a.id,
        organisation_id=org_a_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user_id,
    )
    session.add(ver_a)
    session.flush()

    doc_a = BrandGuidelineDocument(
        brand_kit_version_id=ver_a.id,
        organisation_id=org_a_id,
        title="Org A Doc",
        document_category=GuidelineDocumentCategory.STYLE_GUIDE,
        original_filename="org_a.pdf",
        stored_filename=f"{uuid.uuid4().hex}.pdf",
        storage_path=f"tenants/{org_a_id}/org_a.pdf",
        mime_type="application/pdf",
        file_size_bytes=2048,
        file_sha256="d" * 64,
    )
    session.add(doc_a)
    session.commit()

    # 1. BrandKitVersion with org_b_id pointing to kit_a (org_a_id) -> rejected
    with pytest.raises(IntegrityError):
        session.add(
            BrandKitVersion(
                brand_kit_id=kit_a.id,
                organisation_id=org_b_id,
                version_number=2,
                status=BrandKitVersionStatus.DRAFT,
            )
        )
        session.flush()
    session.rollback()

    # 2. BrandIdentity with org_b_id pointing to ver_a (org_a_id) -> rejected
    with pytest.raises(IntegrityError):
        session.add(
            BrandIdentity(
                brand_kit_version_id=ver_a.id,
                organisation_id=org_b_id,
                brand_name="Cross Tenant Identity",
            )
        )
        session.flush()
    session.rollback()

    # 3. ApprovedBrandFact with org_b_id pointing to ver_a (org_a_id) -> rejected
    with pytest.raises(IntegrityError):
        session.add(
            ApprovedBrandFact(
                brand_kit_version_id=ver_a.id,
                organisation_id=org_b_id,
                category=FactCategory.PRICING,
                subject_name="Coffee",
                fact_key="coffee_price",
                fact_value="â‚¹129",
                source_reference="Ref",
            )
        )
        session.flush()
    session.rollback()

    # 4. ComplianceRule with org_b_id pointing to ver_a (org_a_id) -> rejected
    with pytest.raises(IntegrityError):
        session.add(
            ComplianceRule(
                brand_kit_version_id=ver_a.id,
                organisation_id=org_b_id,
                rule_code="R1",
                rule_type=ComplianceRuleType.PROHIBITED_TERM,
                title="Cross Tenant Rule",
                description="Desc",
                target_pattern="best",
                source_reference="Ref",
            )
        )
        session.flush()
    session.rollback()

    # 5. BrandAsset with org_b_id pointing to ver_a (org_a_id) -> rejected
    with pytest.raises(IntegrityError):
        session.add(
            BrandAsset(
                brand_kit_version_id=ver_a.id,
                organisation_id=org_b_id,
                asset_type=BrandAssetType.PRIMARY_LOGO,
                title="Cross Tenant Logo",
                original_filename="logo.png",
                stored_filename="logo.png",
                storage_path="path/logo.png",
                mime_type="image/png",
                file_size_bytes=1024,
                file_sha256="e" * 64,
            )
        )
        session.flush()
    session.rollback()

    # 6. BrandGuidelineDocument with org_b_id pointing to ver_a (org_a_id) -> rejected
    with pytest.raises(IntegrityError):
        session.add(
            BrandGuidelineDocument(
                brand_kit_version_id=ver_a.id,
                organisation_id=org_b_id,
                title="Cross Tenant Doc",
                original_filename="doc.pdf",
                stored_filename="doc.pdf",
                storage_path="path/doc.pdf",
                mime_type="application/pdf",
                file_size_bytes=1024,
                file_sha256="f" * 64,
            )
        )
        session.flush()
    session.rollback()

    # 7. BrandDocumentChunk with org_b_id pointing to doc_a/ver_a (org_a_id) -> rejected
    with pytest.raises(IntegrityError):
        session.add(
            BrandDocumentChunk(
                document_id=doc_a.id,
                brand_kit_version_id=ver_a.id,
                organisation_id=org_b_id,
                chunk_index=0,
                char_start=0,
                char_end=10,
                content="chunk",
                content_sha256="1" * 64,
                token_count=2,
            )
        )
        session.flush()
    session.rollback()

    # 8. BrandAuditLog with org_b_id referencing kit_a (org_a_id) -> rejected by trigger
    with pytest.raises(IntegrityError):
        session.add(
            BrandAuditLog(
                organisation_id=org_b_id,
                brand_kit_id=kit_a.id,
                action="CROSS_TENANT_AUDIT",
                resource_type=BrandAuditResourceType.BRAND_KIT,
                resource_id=kit_a.id,
            )
        )
        session.flush()
    session.rollback()

    # 9. ApprovedBrandFact in Org B referencing source_document_id from Org A -> rejected by trigger
    kit_b = BrandKit(
        organisation_id=org_b_id,
        name="Org B Kit",
        slug=f"org-b-kit-{uuid.uuid4().hex[:6]}",
        created_by_user_id=user_id,
    )
    session.add(kit_b)
    session.flush()
    ver_b = BrandKitVersion(
        brand_kit_id=kit_b.id,
        organisation_id=org_b_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
    )
    session.add(ver_b)
    session.commit()

    with pytest.raises(IntegrityError):
        session.add(
            ApprovedBrandFact(
                brand_kit_version_id=ver_b.id,
                organisation_id=org_b_id,
                category=FactCategory.PRICING,
                subject_name="Org B Product",
                fact_key="org_b_fact",
                fact_value="â‚¹199",
                source_type=ProvenanceSourceType.GUIDELINE_DOCUMENT,
                source_document_id=doc_a.id,  # Belongs to Org A!
                source_reference="Spoofed Doc Ref",
            )
        )
        session.flush()
    session.rollback()

    # 10. Missing organisation_id (NULL) or non-existent parent UUID -> rejected
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                """
                INSERT INTO brand_kits (id, organisation_id, name, slug, is_archived, created_at, updated_at)
                VALUES (:id, NULL, 'No Org', 'no-org', FALSE, NOW(), NOW());
                """
            ),
            {"id": uuid.uuid4()},
        )
    session.rollback()


# ==============================================================================
# C. VERSION CONSTRAINTS & LIFECYCLE TRANSITIONS
# ==============================================================================


def test_version_uniqueness_single_draft_and_status_transitions(pg_tenant_fixture):
    """Verify unique (brand_kit_id, version_number), single DRAFT partial index, and valid status transitions."""
    session = pg_tenant_fixture["session"]
    org_id = pg_tenant_fixture["org_a_id"]
    user_id = pg_tenant_fixture["user_id"]

    kit = BrandKit(
        organisation_id=org_id,
        name="Lifecycle Kit",
        slug=f"lifecycle-kit-{uuid.uuid4().hex[:6]}",
        created_by_user_id=user_id,
    )
    session.add(kit)
    session.flush()

    v1 = BrandKitVersion(
        brand_kit_id=kit.id,
        organisation_id=org_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user_id,
    )
    session.add(v1)
    session.commit()

    # 1. Duplicate version_number (1) for the same BrandKit -> rejected
    with pytest.raises(IntegrityError):
        session.add(
            BrandKitVersion(
                brand_kit_id=kit.id,
                organisation_id=org_id,
                version_number=1,
                status=BrandKitVersionStatus.DRAFT,
            )
        )
        session.flush()
    session.rollback()

    # 2. Second DRAFT version (version_number=2, status='DRAFT') while v1 is still DRAFT -> rejected by uq_brand_kit_single_draft
    with pytest.raises(IntegrityError):
        session.add(
            BrandKitVersion(
                brand_kit_id=kit.id,
                organisation_id=org_id,
                version_number=2,
                status=BrandKitVersionStatus.DRAFT,
            )
        )
        session.flush()
    session.rollback()

    # 3. Direct transition DRAFT -> ARCHIVED is rejected by trigger
    with pytest.raises(IntegrityError) as exc_info:
        v1.status = BrandKitVersionStatus.ARCHIVED
        session.flush()
    assert "P0003" in str(exc_info.value)
    session.rollback()

    # 4. Setting brand_kits.active_version_id to a DRAFT version is rejected by trigger
    with pytest.raises(IntegrityError) as exc_info:
        kit.active_version_id = v1.id
        session.flush()
    assert "P0003" in str(exc_info.value)
    session.rollback()

    # 5. Valid transition: v1 DRAFT -> PUBLISHED, and setting kit.active_version_id = v1.id succeeds
    v1_db = session.get(BrandKitVersion, v1.id)
    kit_db = session.get(BrandKit, kit.id)
    v1_db.status = BrandKitVersionStatus.PUBLISHED
    v1_db.published_by_user_id = user_id
    session.flush()
    session.refresh(v1_db)
    assert v1_db.published_at is not None

    kit_db.active_version_id = v1_db.id
    session.commit()

    # 6. Now that v1 is PUBLISHED, creating a new DRAFT v2 succeeds (one PUBLISHED + one DRAFT allowed)
    v2 = BrandKitVersion(
        brand_kit_id=kit.id,
        organisation_id=org_id,
        version_number=2,
        status=BrandKitVersionStatus.DRAFT,
        cloned_from_version_id=v1.id,
        created_by_user_id=user_id,
    )
    session.add(v2)
    session.commit()

    # 7. A kit cannot have two PUBLISHED versions (uq_brand_kit_single_published)
    # 7a. Attempting to promote v2 (DRAFT -> PUBLISHED) while v1 is still PUBLISHED is rejected
    with pytest.raises(IntegrityError):
        v2_db = session.get(BrandKitVersion, v2.id)
        v2_db.status = BrandKitVersionStatus.PUBLISHED
        session.flush()
    session.rollback()

        # 7b. Direct creation of a PUBLISHED version is rejected by the ORM.
    with pytest.raises(IntegrityError) as exc_info:
        session.add(
            BrandKitVersion(
                brand_kit_id=kit.id,
                organisation_id=org_id,
                version_number=3,
                status=BrandKitVersionStatus.PUBLISHED,
                created_by_user_id=user_id,
            )
        )
        session.flush()

    assert isinstance(exc_info.value.orig, BrandHubImmutabilityError)
    assert "P0003" in str(exc_info.value.orig)
    session.rollback()



    # 8. Archiving the previously PUBLISHED version (v1) and flushing allows v2 (DRAFT) to become PUBLISHED
    v1_db = session.get(BrandKitVersion, v1.id)
    v2_db = session.get(BrandKitVersion, v2.id)
    kit_db = session.get(BrandKit, kit.id)

    v1_db.status = BrandKitVersionStatus.ARCHIVED
    v1_db.archived_by_user_id = user_id
    session.flush()

    v2_db.status = BrandKitVersionStatus.PUBLISHED
    v2_db.published_by_user_id = user_id
    session.flush()
    session.refresh(v2_db)
    assert v2_db.published_at is not None

    kit_db.active_version_id = v2_db.id
    session.commit()

    # 9. Different Brand Kits can each have their own PUBLISHED version simultaneously
    kit_other = BrandKit(
        organisation_id=org_id,
        name="Second Lifecycle Kit",
        slug=f"second-lifecycle-kit-{uuid.uuid4().hex[:6]}",
        created_by_user_id=user_id,
    )
    session.add(kit_other)
    session.flush()

    kit_other_v1 = BrandKitVersion(
        brand_kit_id=kit_other.id,
        organisation_id=org_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user_id,
    )
    session.add(kit_other_v1)
    session.flush()

    # Publish through the permitted DRAFT -> PUBLISHED transition.
    kit_other_v1.status = BrandKitVersionStatus.PUBLISHED
    kit_other_v1.published_by_user_id = user_id
    kit_other_v1.published_at = utcnow()
    session.flush()
    kit_other.active_version_id = kit_other_v1.id
    session.commit()


# ==============================================================================
# D. PUBLISHED & ARCHIVED IMMUTABILITY & DOCUMENT TELEMETRY ALLOWLIST
# ==============================================================================


def test_published_and_archived_immutability_and_doc_telemetry_allowlist(pg_tenant_fixture):
    """Verify published & archived versions and their children cannot be mutated, except allowlisted doc telemetry."""
    session = pg_tenant_fixture["session"]
    org_id = pg_tenant_fixture["org_a_id"]
    user_id = pg_tenant_fixture["user_id"]

    kit = BrandKit(
        organisation_id=org_id,
        name="Immutable Brand Kit",
        slug=f"immutable-kit-{uuid.uuid4().hex[:6]}",
        created_by_user_id=user_id,
    )
    session.add(kit)
    session.flush()

    version = BrandKitVersion(
        brand_kit_id=kit.id,
        organisation_id=org_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        changelog="Initial v1 release",
        created_by_user_id=user_id,
    )
    session.add(version)
    session.flush()

    identity = BrandIdentity(
        brand_kit_version_id=version.id,
        organisation_id=org_id,
        brand_name="Inkloom Coffee",
        tagline="Pure Roast",
        primary_color_hex="#2C1810",
    )
    fact = ApprovedBrandFact(
        brand_kit_version_id=version.id,
        organisation_id=org_id,
        category=FactCategory.PRICING,
        subject_name="Premium Coffee",
        fact_key="premium_coffee_mrp",
        fact_value="â‚¹129",
        currency="INR",
        numeric_value=Decimal("129.0000"),
        source_type=ProvenanceSourceType.MANUAL_ENTRY,
        source_reference="Price Card 2026",
        approval_status=FactRuleApprovalStatus.APPROVED,
    )
    rule = ComplianceRule(
        brand_kit_version_id=version.id,
        organisation_id=org_id,
        rule_code="NO_SUPERLATIVES",
        rule_type=ComplianceRuleType.PROHIBITED_TERM,
        priority=10,
        severity=RuleSeverity.CRITICAL,
        title="No Unverified Superlatives",
        description="Avoid claiming 'best coffee in Punjab'",
        target_pattern="best coffee",
        source_reference="ASCI Guidelines",
        approval_status=FactRuleApprovalStatus.APPROVED,
    )
    asset = BrandAsset(
        brand_kit_version_id=version.id,
        organisation_id=org_id,
        asset_type=BrandAssetType.PRIMARY_LOGO,
        title="Primary Logo",
        original_filename="logo.png",
        stored_filename="uuid-logo.png",
        storage_path=f"tenants/{org_id}/assets/uuid-logo.png",
        mime_type="image/png",
        file_size_bytes=8192,
        file_sha256="1" * 64,
    )
    doc = BrandGuidelineDocument(
        brand_kit_version_id=version.id,
        organisation_id=org_id,
        title="Brand Book 2026",
        document_category=GuidelineDocumentCategory.BRAND_BOOK,
        original_filename="brand_book.pdf",
        stored_filename="uuid-brand-book.pdf",
        storage_path=f"tenants/{org_id}/docs/uuid-brand-book.pdf",
        mime_type="application/pdf",
        file_size_bytes=65536,
        file_sha256="2" * 64,
        parsing_status=DocumentParsingStatus.PENDING,
    )
    session.add_all([identity, fact, rule, asset, doc])
    session.flush()

    chunk = BrandDocumentChunk(
        document_id=doc.id,
        brand_kit_version_id=version.id,
        organisation_id=org_id,
        chunk_index=0,
        page_number=1,
        char_start=0,
        char_end=50,
        content="Initial chunk text",
        content_sha256="3" * 64,
        token_count=5,
    )
    audit = BrandAuditLog(
        organisation_id=org_id,
        actor_user_id=user_id,
        brand_kit_id=kit.id,
        brand_kit_version_id=version.id,
        action="BRAND_KIT_VERSION_PUBLISHED",
        resource_type=BrandAuditResourceType.VERSION,
        resource_id=version.id,
        details_json={"version_number": 1},
    )
    session.add_all([chunk, audit])
    session.flush()

    # Publish version 1 and set as active_version_id
    version.status = BrandKitVersionStatus.PUBLISHED
    version.published_by_user_id = user_id
    session.flush()
    kit.active_version_id = version.id
    session.commit()

    # --- 1. Mutating or deleting PUBLISHED version is rejected ---
    with pytest.raises(IntegrityError) as exc_info:
        session.execute(
            text("UPDATE brand_kit_versions SET changelog = 'Tampered' WHERE id = :id;"),
            {"id": version.id},
        )
    assert "P0001" in str(exc_info.value)
    session.rollback()

    with pytest.raises(IntegrityError) as exc_info:
        session.execute(
            text("UPDATE brand_kit_versions SET status = 'DRAFT' WHERE id = :id;"),
            {"id": version.id},
        )
    assert "P0001" in str(exc_info.value)
    session.rollback()

    with pytest.raises(IntegrityError) as exc_info:
        session.execute(
            text("DELETE FROM brand_kit_versions WHERE id = :id;"),
            {"id": version.id},
        )
    assert "P0001" in str(exc_info.value)
    session.rollback()

    # --- 2. Mutating, inserting, or deleting children of PUBLISHED version is rejected ---
    with pytest.raises(IntegrityError) as exc_info:
        session.execute(
            text("UPDATE brand_identities SET brand_name = 'Tampered' WHERE id = :id;"),
            {"id": identity.id},
        )
    assert "P0002" in str(exc_info.value)
    session.rollback()

    with pytest.raises(IntegrityError) as exc_info:
        session.execute(
            text("UPDATE approved_brand_facts SET fact_value = 'â‚¹99' WHERE id = :id;"),
            {"id": fact.id},
        )
    assert "P0002" in str(exc_info.value)
    session.rollback()

    with pytest.raises(IntegrityError) as exc_info:
        session.execute(
            text("DELETE FROM approved_brand_facts WHERE id = :id;"),
            {"id": fact.id},
        )
    assert "P0002" in str(exc_info.value)
    session.rollback()

    with pytest.raises(IntegrityError) as exc_info:
        session.add(
            ComplianceRule(
                brand_kit_version_id=version.id,
                organisation_id=org_id,
                rule_code="NEW_RULE_ON_PUBLISHED",
                rule_type=ComplianceRuleType.PROHIBITED_TERM,
                title="Illegal Insert",
                description="Desc",
                target_pattern="foo",
                source_reference="Ref",
            )
        )
        session.flush()
    assert "P0002" in str(exc_info.value)
    session.rollback()

    with pytest.raises(IntegrityError) as exc_info:
        session.execute(
            text("DELETE FROM brand_assets WHERE id = :id;"),
            {"id": asset.id},
        )
    assert "P0002" in str(exc_info.value)
    session.rollback()

    with pytest.raises(IntegrityError) as exc_info:
        session.execute(
            text("UPDATE brand_document_chunks SET content = 'Tampered chunk' WHERE id = :id;"),
            {"id": chunk.id},
        )
    assert "P0002" in str(exc_info.value)
    session.rollback()

    # --- 3. Guideline Document: locked identity columns rejected, allowlisted telemetry columns succeed ---
    for locked_col, bad_val in [
        ("file_sha256", "'9999999999999999999999999999999999999999999999999999999999999999'"),
        ("storage_path", "'tenants/spoofed/path.pdf'"),
        ("original_filename", "'hacked.pdf'"),
        ("stored_filename", "'hacked.pdf'"),
        ("mime_type", "'text/plain'"),
        ("file_size_bytes", "999"),
        ("title", "'Tampered Title'"),
        ("document_category", "'LEGAL_POLICY'"),
    ]:
        with pytest.raises(IntegrityError) as exc_info:
            session.execute(
                text(f"UPDATE brand_guideline_documents SET {locked_col} = {bad_val} WHERE id = :id;"),
                {"id": doc.id},
            )
        assert "P0002" in str(exc_info.value)
        session.rollback()

    with pytest.raises(IntegrityError) as exc_info:
        session.execute(
            text("DELETE FROM brand_guideline_documents WHERE id = :id;"),
            {"id": doc.id},
        )
    assert "P0002" in str(exc_info.value)
    session.rollback()

    # Allowlisted processing telemetry update on PUBLISHED version MUST succeed
    now_ts = utcnow()
    session.execute(
        text(
            """
            UPDATE brand_guideline_documents
            SET parsing_status = 'EMBEDDED',
                parse_attempt_count = 1,
                last_error_code = NULL,
                last_error_message = NULL,
                page_count = 12,
                raw_text_content = 'Extracted official brand guidelines text.',
                embedding_model = 'BAAI/bge-large-en-v1.5',
                embedding_model_version = '1.5',
                parsed_at = :now_ts,
                embedded_at = :now_ts
            WHERE id = :id;
            """
        ),
        {"id": doc.id, "now_ts": now_ts},
    )
    session.commit()

    refreshed_doc = session.get(BrandGuidelineDocument, doc.id)
    assert refreshed_doc.parsing_status == "EMBEDDED"
    assert refreshed_doc.parse_attempt_count == 1
    assert refreshed_doc.page_count == 12
    assert refreshed_doc.raw_text_content == "Extracted official brand guidelines text."
    assert refreshed_doc.embedding_model == "BAAI/bge-large-en-v1.5"
    assert refreshed_doc.file_sha256 == "2" * 64

    # --- 4. Transition PUBLISHED -> ARCHIVED clears active_version_id and is permanently terminal ---
    session.execute(
        text(
            """
            UPDATE brand_kit_versions
            SET status = 'ARCHIVED', archived_by_user_id = :uid
            WHERE id = :id;
            """
        ),
        {"id": version.id, "uid": user_id},
    )
    session.commit()

    session.expire_all()
    archived_ver = session.get(BrandKitVersion, version.id)
    updated_kit = session.get(BrandKit, kit.id)
    assert archived_ver.status == BrandKitVersionStatus.ARCHIVED
    assert archived_ver.archived_at is not None
    assert updated_kit.active_version_id is None

    # Attempting to restore ARCHIVED -> PUBLISHED or DRAFT is rejected
    for target_state in ("PUBLISHED", "DRAFT"):
        with pytest.raises(IntegrityError) as exc_info:
            session.execute(
                text("UPDATE brand_kit_versions SET status = :st WHERE id = :id;"),
                {"st": target_state, "id": version.id},
            )
        assert "P0003" in str(exc_info.value)
        session.rollback()

    # --- 5. BrandAuditLog is append-only (UPDATE and DELETE are rejected) ---
    with pytest.raises(IntegrityError) as exc_info:
        session.execute(
            text("UPDATE brand_audit_logs SET action = 'TAMPERED' WHERE id = :id;"),
            {"id": audit.id},
        )
    assert "P0005" in str(exc_info.value)
    session.rollback()

    with pytest.raises(IntegrityError) as exc_info:
        session.execute(
            text("DELETE FROM brand_audit_logs WHERE id = :id;"),
            {"id": audit.id},
        )
    assert "P0005" in str(exc_info.value)
    session.rollback()


def test_postgres_guideline_document_reassignment_both_directions_rejected(pg_tenant_fixture):
    """Verify PostgreSQL trigger fn_enforce_guideline_doc_immutability blocks moving a guideline document
    both out of a PUBLISHED/ARCHIVED version into a DRAFT version and from a DRAFT version into a PUBLISHED/ARCHIVED version.
    """
    session = pg_tenant_fixture["session"]
    org_id = pg_tenant_fixture["org_a_id"]
    user_id = pg_tenant_fixture["user_id"]

    kit = BrandKit(
        organisation_id=org_id,
        name="Doc Reassign Kit",
        slug=f"doc-reassign-kit-{uuid.uuid4().hex[:6]}",
        created_by_user_id=user_id,
    )
    session.add(kit)
    session.flush()

    v1_pub = BrandKitVersion(
        brand_kit_id=kit.id,
        organisation_id=org_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user_id,
    )
    session.add(v1_pub)
    session.flush()

    doc_in_v1 = BrandGuidelineDocument(
        brand_kit_version_id=v1_pub.id,
        organisation_id=org_id,
        title="Published Version Doc",
        document_category=GuidelineDocumentCategory.BRAND_BOOK,
        original_filename="v1_book.pdf",
        stored_filename="uuid-v1-book.pdf",
        storage_path=f"tenants/{org_id}/docs/uuid-v1-book.pdf",
        mime_type="application/pdf",
        file_size_bytes=16384,
        file_sha256="4" * 64,
        parsing_status=DocumentParsingStatus.PENDING,
    )
    session.add(doc_in_v1)
    session.flush()

    v1_pub.status = BrandKitVersionStatus.PUBLISHED
    v1_pub.published_by_user_id = user_id
    session.flush()

    v2_draft = BrandKitVersion(
        brand_kit_id=kit.id,
        organisation_id=org_id,
        version_number=2,
        status=BrandKitVersionStatus.DRAFT,
        cloned_from_version_id=v1_pub.id,
        created_by_user_id=user_id,
    )
    session.add(v2_draft)
    session.flush()

    doc_in_v2 = BrandGuidelineDocument(
        brand_kit_version_id=v2_draft.id,
        organisation_id=org_id,
        title="Draft Version Doc",
        document_category=GuidelineDocumentCategory.STYLE_GUIDE,
        original_filename="v2_guide.pdf",
        stored_filename="uuid-v2-guide.pdf",
        storage_path=f"tenants/{org_id}/docs/uuid-v2-guide.pdf",
        mime_type="application/pdf",
        file_size_bytes=16384,
        file_sha256="5" * 64,
        parsing_status=DocumentParsingStatus.PENDING,
    )
    session.add(doc_in_v2)
    session.commit()

    # 1. Raw SQL: moving doc_in_v1 OUT of PUBLISHED v1_pub into DRAFT v2_draft is rejected by PostgreSQL trigger
    with pytest.raises(IntegrityError) as exc_info:
        session.execute(
            text("UPDATE brand_guideline_documents SET brand_kit_version_id = :v2_id WHERE id = :doc_id;"),
            {"v2_id": v2_draft.id, "doc_id": doc_in_v1.id},
        )
    assert "P0002" in str(exc_info.value)
    session.rollback()

    # 2. Raw SQL: moving doc_in_v2 FROM DRAFT v2_draft INTO PUBLISHED v1_pub is rejected by PostgreSQL trigger
    with pytest.raises(IntegrityError) as exc_info:
        session.execute(
            text("UPDATE brand_guideline_documents SET brand_kit_version_id = :v1_id WHERE id = :doc_id;"),
            {"v1_id": v1_pub.id, "doc_id": doc_in_v2.id},
        )
    assert "P0002" in str(exc_info.value)
    session.rollback()

    # 3. Archive v1_pub (PUBLISHED -> ARCHIVED) and verify both directions remain blocked for ARCHIVED version
    session.execute(
        text("UPDATE brand_kit_versions SET status = 'ARCHIVED', archived_by_user_id = :uid WHERE id = :id;"),
        {"id": v1_pub.id, "uid": user_id},
    )
    session.commit()

    with pytest.raises(IntegrityError) as exc_info:
        session.execute(
            text("UPDATE brand_guideline_documents SET brand_kit_version_id = :v2_id WHERE id = :doc_id;"),
            {"v2_id": v2_draft.id, "doc_id": doc_in_v1.id},
        )
    assert "P0002" in str(exc_info.value)
    session.rollback()

    with pytest.raises(IntegrityError) as exc_info:
        session.execute(
            text("UPDATE brand_guideline_documents SET brand_kit_version_id = :v1_id WHERE id = :doc_id;"),
            {"v1_id": v1_pub.id, "doc_id": doc_in_v2.id},
        )
    assert "P0002" in str(exc_info.value)
    session.rollback()


# ==============================================================================
# E. DOWNGRADE & RE-UPGRADE SAFETY
# ==============================================================================


def test_migration_0003_downgrade_and_reupgrade_safety(pg_engine):
    """Verify downgrading 0005 -> 0004 -> 0003 -> 0002 and re-upgrading to 0005 head works cleanly without data or RBAC loss."""
    from app.core.config import settings

    backend_dir = Path(__file__).resolve().parents[1]
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    alembic_cfg.set_main_option("path_separator", "os")

    orig_db_url = settings.DATABASE_URL
    orig_fallback = settings.ALLOW_SQLITE_DEV_FALLBACK
    settings.DATABASE_URL = POSTGRES_TEST_URI
    settings.ALLOW_SQLITE_DEV_FALLBACK = False

    pg_engine.dispose()
    try:
        # 1. Downgrade 0005_guideline_doc_reassignment -> 0004_single_published_version -> 0003_phase3_brand_hub
        command.downgrade(alembic_cfg, "0004_single_published_version")
        with pg_engine.connect() as conn:
            rev_at_0004 = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
            assert rev_at_0004 == "0004_single_published_version"

        pg_engine.dispose()

        command.downgrade(alembic_cfg, "0003_phase3_brand_hub")

        with pg_engine.connect() as conn:
            rev_at_0003 = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
            assert rev_at_0003 == "0003_phase3_brand_hub"

            indexes_at_0003 = {
                row[0]
                for row in conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename = 'brand_kit_versions';")
                ).fetchall()
            }
            assert "uq_brand_kit_single_published" not in indexes_at_0003
            assert "uq_brand_kit_single_draft" in indexes_at_0003

        pg_engine.dispose()

        # 2. Downgrade 0003_phase3_brand_hub -> 0002_organisation_invitations
        command.downgrade(alembic_cfg, "0002_organisation_invitations")

        with pg_engine.connect() as conn:
            rev_after_downgrade = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
            assert rev_after_downgrade == "0002_organisation_invitations"

            tables_after_downgrade = {
                row[0]
                for row in conn.execute(
                    text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
                ).fetchall()
            }
            # Phase 3 tables must be gone
            assert "brand_kits" not in tables_after_downgrade
            assert "brand_kit_versions" not in tables_after_downgrade
            assert "brand_document_chunks" not in tables_after_downgrade

            # Phase 2 tables and permissions must still exist intact
            assert {
                "users",
                "organisations",
                "roles",
                "permissions",
                "role_permissions",
                "organisation_invitations",
            }.issubset(tables_after_downgrade)
            perm_codes = {
                row[0]
                for row in conn.execute(text("SELECT code FROM permissions;")).fetchall()
            }
            assert {
                PermissionCode.BRAND_READ,
                PermissionCode.BRAND_MANAGE,
                PermissionCode.AUDIT_READ,
            }.issubset(perm_codes)

        pg_engine.dispose()

        # 3. Re-upgrade to head (0007_content_approvals)
        command.upgrade(alembic_cfg, "head")

        with pg_engine.connect() as conn:
            rev_after_reupgrade = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
            assert rev_after_reupgrade in ("0006_compliance_workflow", "0007_content_approvals")

            tables_after_reupgrade = {
                row[0]
                for row in conn.execute(
                    text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
                ).fetchall()
            }
            assert {
                "brand_kits",
                "brand_kit_versions",
                "brand_identities",
                "approved_brand_facts",
                "compliance_rules",
                "brand_assets",
                "brand_guideline_documents",
                "brand_document_chunks",
                "brand_audit_logs",
            }.issubset(tables_after_reupgrade)

            indexes_after_reupgrade = {
                row[0]
                for row in conn.execute(
                    text("SELECT indexname FROM pg_indexes WHERE tablename = 'brand_kit_versions';")
                ).fetchall()
            }
            assert "uq_brand_kit_single_draft" in indexes_after_reupgrade
            assert "uq_brand_kit_single_published" in indexes_after_reupgrade
    finally:
        settings.DATABASE_URL = orig_db_url
        settings.ALLOW_SQLITE_DEV_FALLBACK = orig_fallback


# ==============================================================================
# F. DEDICATED ORM SESSION.BEFORE_FLUSH IMMUTABILITY LISTENER TESTS (SQLITE)
# ==============================================================================


def _seed_sqlite_tenant_and_kit(db_session):
    """Create a user, organisation, and BrandKit on the in-memory SQLite session (where no PG triggers exist)."""
    user = User(
        id=uuid.uuid4(),
        full_name="ORM Listener Tester",
        email=f"orm_listener_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="argon2_test_hash",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    db_session.flush()

    org = Organisation(
        id=uuid.uuid4(),
        name=f"SQLite Org {uuid.uuid4().hex[:6]}",
        slug=f"sqlite-org-{uuid.uuid4().hex[:6]}",
        created_by=user.id,
    )
    db_session.add(org)
    db_session.flush()

    kit = BrandKit(
        organisation_id=org.id,
        name="SQLite Brand Kit",
        slug=f"sqlite-kit-{uuid.uuid4().hex[:6]}",
        created_by_user_id=user.id,
    )
    db_session.add(kit)
    db_session.commit()
    return user.id, org.id, kit.id


def _create_all_six_children(db_session, version_id: uuid.UUID, org_id: uuid.UUID, suffix: str = "1"):
    """Create and flush all 6 version-scoped child models under the specified BrandKitVersion."""
    identity = BrandIdentity(
        brand_kit_version_id=version_id,
        organisation_id=org_id,
        brand_name=f"Brand {suffix}",
        tagline=f"Tagline {suffix}",
        primary_color_hex="#112233",
    )
    fact = ApprovedBrandFact(
        brand_kit_version_id=version_id,
        organisation_id=org_id,
        category=FactCategory.PRICING,
        subject_name=f"Product {suffix}",
        fact_key=f"fact_key_{suffix}",
        fact_value="â‚¹199",
        currency="INR",
        numeric_value=Decimal("199.0000"),
        source_type=ProvenanceSourceType.MANUAL_ENTRY,
        source_reference="Price Sheet",
        approval_status=FactRuleApprovalStatus.APPROVED,
    )
    rule = ComplianceRule(
        brand_kit_version_id=version_id,
        organisation_id=org_id,
        rule_code=f"RULE_{suffix}",
        rule_type=ComplianceRuleType.PROHIBITED_TERM,
        priority=10,
        severity=RuleSeverity.HIGH,
        title=f"Rule {suffix}",
        description="Prohibited phrase",
        target_pattern="guaranteed cure",
        source_reference="Policy Ref",
        approval_status=FactRuleApprovalStatus.APPROVED,
    )
    asset = BrandAsset(
        brand_kit_version_id=version_id,
        organisation_id=org_id,
        asset_type=BrandAssetType.PRIMARY_LOGO,
        title=f"Logo {suffix}",
        original_filename=f"logo_{suffix}.png",
        stored_filename=f"uuid-logo-{suffix}.png",
        storage_path=f"tenants/{org_id}/assets/uuid-logo-{suffix}.png",
        mime_type="image/png",
        file_size_bytes=4096,
        file_sha256="a" * 64,
    )
    doc = BrandGuidelineDocument(
        brand_kit_version_id=version_id,
        organisation_id=org_id,
        title=f"Guideline {suffix}",
        document_category=GuidelineDocumentCategory.BRAND_BOOK,
        original_filename=f"book_{suffix}.pdf",
        stored_filename=f"uuid-book-{suffix}.pdf",
        storage_path=f"tenants/{org_id}/docs/uuid-book-{suffix}.pdf",
        mime_type="application/pdf",
        file_size_bytes=32768,
        file_sha256="b" * 64,
        parsing_status=DocumentParsingStatus.PENDING,
    )
    db_session.add_all([identity, fact, rule, asset, doc])
    db_session.flush()

    chunk = BrandDocumentChunk(
        document_id=doc.id,
        brand_kit_version_id=version_id,
        organisation_id=org_id,
        chunk_index=0,
        page_number=1,
        char_start=0,
        char_end=24,
        content=f"Chunk content {suffix}",
        content_sha256="c" * 64,
        token_count=4,
    )
    db_session.add(chunk)
    db_session.flush()
    return {
        "identity": identity,
        "fact": fact,
        "rule": rule,
        "asset": asset,
        "doc": doc,
        "chunk": chunk,
    }


def test_orm_listener_expired_published_version_changed_to_draft_rejected(db_session):
    """Scenario 1 & 12: Expired PUBLISHED BrandKitVersion changed to DRAFT (or structural fields mutated)
    after both session.commit() and session.expire_all() is rejected by the ORM listener with [P0001].
    """
    user_id, org_id, kit_id = _seed_sqlite_tenant_and_kit(db_session)

    ver = BrandKitVersion(
        brand_kit_id=kit_id,
        organisation_id=org_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user_id,
        changelog="Initial v1",
    )
    db_session.add(ver)
    db_session.flush()

    # Publish through the permitted DRAFT -> PUBLISHED transition.
    ver.status = BrandKitVersionStatus.PUBLISHED
    ver.published_by_user_id = user_id
    ver.published_at = utcnow()
    db_session.commit()

    # session.commit() expires all attributes on ver (expire_on_commit=True)
    ver_id = inspect(ver).identity[0]
    assert "status" not in inspect(ver).dict

    # 1a. Immediately after session.commit() (expired), assign status = DRAFT without reading ver.status
    ver.status = BrandKitVersionStatus.DRAFT
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert isinstance(exc_info.value.orig, BrandHubImmutabilityError)
    assert "P0001" in str(exc_info.value.orig)
    db_session.rollback()

    # 1b. Explicitly call session.expire_all(), then assign status = DRAFT and changelog = 'Tampered'
    ver = db_session.get(BrandKitVersion, ver_id)
    db_session.expire_all()
    assert "status" not in inspect(ver).dict
    ver.status = BrandKitVersionStatus.DRAFT
    ver.changelog = "Tampered"
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert isinstance(exc_info.value.orig, BrandHubImmutabilityError)
    assert "P0001" in str(exc_info.value.orig)
    db_session.rollback()

    # 1c. Structural column mutation (version_number) while expired is rejected with [P0001]
    ver = db_session.get(BrandKitVersion, ver_id)
    db_session.expire_all()
    ver.version_number = 99
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert isinstance(exc_info.value.orig, BrandHubImmutabilityError)
    assert "P0001" in str(exc_info.value.orig)
    db_session.rollback()

    refreshed = db_session.get(BrandKitVersion, ver_id)
    assert refreshed.status == BrandKitVersionStatus.PUBLISHED
    assert refreshed.version_number == 1
    assert refreshed.changelog == "Initial v1"


def test_orm_listener_expired_archived_version_changed_to_published_or_draft_rejected(db_session):
    """Scenario 2 & 12: Expired ARCHIVED BrandKitVersion changed to PUBLISHED or DRAFT (or edited)
    after both session.commit() and session.expire_all() is rejected with [P0003].
    """
    user_id, org_id, kit_id = _seed_sqlite_tenant_and_kit(db_session)

    ver = BrandKitVersion(
        brand_kit_id=kit_id,
        organisation_id=org_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user_id,
    )
    db_session.add(ver)
    db_session.flush()

    # Publish through the permitted DRAFT -> PUBLISHED transition.
    ver.status = BrandKitVersionStatus.PUBLISHED
    ver.published_by_user_id = user_id
    ver.published_at = utcnow()
    db_session.commit()

    ver.status = BrandKitVersionStatus.ARCHIVED
    ver.archived_by_user_id = user_id
    ver.archived_at = utcnow()
    # session.commit() expires all attributes on ver
    db_session.commit()
    ver_id = inspect(ver).identity[0]
    assert "status" not in inspect(ver).dict

    # 2a. Expired after commit(): attempt ARCHIVED -> PUBLISHED
    ver.status = BrandKitVersionStatus.PUBLISHED
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert isinstance(exc_info.value.orig, BrandHubImmutabilityError)
    assert "P0003" in str(exc_info.value.orig)
    db_session.rollback()

    # 2b. Expired after expire_all(): attempt ARCHIVED -> DRAFT
    ver = db_session.get(BrandKitVersion, ver_id)
    db_session.expire_all()
    assert "status" not in inspect(ver).dict
    ver.status = BrandKitVersionStatus.DRAFT
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert isinstance(exc_info.value.orig, BrandHubImmutabilityError)
    assert "P0003" in str(exc_info.value.orig)
    db_session.rollback()

    # 2c. Expired after expire_all(): attempt modifying changelog on ARCHIVED version
    ver = db_session.get(BrandKitVersion, ver_id)
    db_session.expire_all()
    ver.changelog = "Edited after archive"
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert isinstance(exc_info.value.orig, BrandHubImmutabilityError)
    assert "P0003" in str(exc_info.value.orig)
    db_session.rollback()

    refreshed = db_session.get(BrandKitVersion, ver_id)
    assert refreshed.status == BrandKitVersionStatus.ARCHIVED


def test_orm_listener_expired_published_and_archived_version_deletion_rejected(db_session):
    """Scenario 3 & 12: Deleting an expired PUBLISHED or ARCHIVED BrandKitVersion (even if status is
    overwritten to DRAFT while expired before delete) is rejected with [P0001].
    """
    user_id, org_id, kit_id = _seed_sqlite_tenant_and_kit(db_session)

    ver = BrandKitVersion(
        brand_kit_id=kit_id,
        organisation_id=org_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user_id,
    )
    db_session.add(ver)
    db_session.flush()

    # Publish through the permitted DRAFT -> PUBLISHED transition.
    ver.status = BrandKitVersionStatus.PUBLISHED
    ver.published_by_user_id = user_id
    ver.published_at = utcnow()
    db_session.commit()
    ver_id = inspect(ver).identity[0]

    # 3a. Expired PUBLISHED version deleted after commit()
    assert "status" not in inspect(ver).dict
    db_session.delete(ver)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert isinstance(exc_info.value.orig, BrandHubImmutabilityError)
    assert "P0001" in str(exc_info.value.orig)
    db_session.rollback()

    # 3b. Expired PUBLISHED version with status overwritten to DRAFT right before delete after expire_all()
    ver = db_session.get(BrandKitVersion, ver_id)
    db_session.expire_all()
    assert "status" not in inspect(ver).dict
    ver.status = BrandKitVersionStatus.DRAFT
    db_session.delete(ver)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert isinstance(exc_info.value.orig, BrandHubImmutabilityError)
    assert "P0001" in str(exc_info.value.orig)
    db_session.rollback()

    # 3c. Archive version, expire, and attempt deletion
    ver = db_session.get(BrandKitVersion, ver_id)
    ver.status = BrandKitVersionStatus.ARCHIVED
    ver.archived_by_user_id = user_id
    ver.archived_at = utcnow()
    db_session.commit()
    db_session.expire_all()

    db_session.delete(ver)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert isinstance(exc_info.value.orig, BrandHubImmutabilityError)
    assert "P0001" in str(exc_info.value.orig)
    db_session.rollback()

    assert db_session.get(BrandKitVersion, ver_id) is not None


def test_orm_listener_expired_child_reassignment_from_published_and_archived_to_draft_rejected(db_session):
    """Scenario 4 & 12: Reassigning any of the 6 child models out of a PUBLISHED/ARCHIVED version into a DRAFT
    version (or from a DRAFT version into a PUBLISHED/ARCHIVED version) when expired after commit() and
    expire_all() is rejected with [P0002].
    """
    user_id, org_id, kit_id = _seed_sqlite_tenant_and_kit(db_session)

    v1 = BrandKitVersion(
        brand_kit_id=kit_id,
        organisation_id=org_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user_id,
    )
    db_session.add(v1)
    db_session.flush()
    v1_children = _create_all_six_children(db_session, v1.id, org_id, suffix="pub")

    v1.status = BrandKitVersionStatus.PUBLISHED
    v1.published_by_user_id = user_id
    v1.published_at = utcnow()
    db_session.flush()

    v2_draft = BrandKitVersion(
        brand_kit_id=kit_id,
        organisation_id=org_id,
        version_number=2,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user_id,
    )
    db_session.add(v2_draft)
    db_session.flush()
    v2_children = _create_all_six_children(db_session, v2_draft.id, org_id, suffix="draft")

    v1_id = v1.id
    v2_id = v2_draft.id
    v1_child_ids = {k: (type(obj), obj.id) for k, obj in v1_children.items()}
    v2_child_ids = {k: (type(obj), obj.id) for k, obj in v2_children.items()}
    # Commit so all objects are expired
    db_session.commit()

    # 4a. Moving each of the 6 children out of PUBLISHED v1 into DRAFT v2 while expired (after commit and expire_all)
    for label, (model_cls, child_id) in v1_child_ids.items():
        child_obj = db_session.get(model_cls, child_id)
        db_session.expire_all()
        assert "brand_kit_version_id" not in inspect(child_obj).dict
        child_obj.brand_kit_version_id = v2_id
        with pytest.raises(IntegrityError) as exc_info:
            db_session.flush()
        assert isinstance(exc_info.value.orig, BrandHubImmutabilityError), f"Failed for {label}"
        assert "P0002" in str(exc_info.value.orig)
        db_session.rollback()

    # 4b. Moving each of the 6 children from DRAFT v2 into PUBLISHED v1 while expired
    for label, (model_cls, child_id) in v2_child_ids.items():
        child_obj = db_session.get(model_cls, child_id)
        db_session.expire_all()
        assert "brand_kit_version_id" not in inspect(child_obj).dict
        child_obj.brand_kit_version_id = v1_id
        with pytest.raises(IntegrityError) as exc_info:
            db_session.flush()
        assert isinstance(exc_info.value.orig, BrandHubImmutabilityError), f"Failed for {label}"
        assert "P0002" in str(exc_info.value.orig)
        db_session.rollback()

    # 4c. Archive v1 and verify moving expired children out of ARCHIVED v1 into DRAFT v2 is also rejected
    v1_obj = db_session.get(BrandKitVersion, v1_id)
    v1_obj.status = BrandKitVersionStatus.ARCHIVED
    v1_obj.archived_by_user_id = user_id
    v1_obj.archived_at = utcnow()
    db_session.commit()

    for label, (model_cls, child_id) in v1_child_ids.items():
        child_obj = db_session.get(model_cls, child_id)
        db_session.expire_all()
        child_obj.brand_kit_version_id = v2_id
        with pytest.raises(IntegrityError) as exc_info:
            db_session.flush()
        assert isinstance(exc_info.value.orig, BrandHubImmutabilityError), f"Failed for {label}"
        assert "P0002" in str(exc_info.value.orig)
        db_session.rollback()


def test_orm_listener_expired_child_update_and_delete_under_published_and_archived_parent_rejected(db_session):
    """Scenario 5 & 12: Updating, deleting, or inserting any of the 6 child models under an expired
    PUBLISHED or ARCHIVED parent version is rejected with [P0002] without lazy-loading child.version.
    """
    user_id, org_id, kit_id = _seed_sqlite_tenant_and_kit(db_session)

    v1 = BrandKitVersion(
        brand_kit_id=kit_id,
        organisation_id=org_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user_id,
    )
    db_session.add(v1)
    db_session.flush()
    children = _create_all_six_children(db_session, v1.id, org_id, suffix="imm")

    v1.status = BrandKitVersionStatus.PUBLISHED
    v1.published_by_user_id = user_id
    v1.published_at = utcnow()
    db_session.commit()

    v1_id = inspect(v1).identity[0]
    child_specs = [
        (BrandIdentity, inspect(children["identity"]).identity[0], "brand_name", "Tampered Brand"),
        (ApprovedBrandFact, inspect(children["fact"]).identity[0], "fact_value", "â‚¹999"),
        (ComplianceRule, inspect(children["rule"]).identity[0], "title", "Tampered Rule"),
        (BrandAsset, inspect(children["asset"]).identity[0], "title", "Tampered Asset"),
        (BrandGuidelineDocument, inspect(children["doc"]).identity[0], "title", "Tampered Doc"),
        (BrandDocumentChunk, inspect(children["chunk"]).identity[0], "content", "Tampered Chunk"),
    ]

    for target_status in (BrandKitVersionStatus.PUBLISHED, BrandKitVersionStatus.ARCHIVED):
        if target_status == BrandKitVersionStatus.ARCHIVED:
            v1_obj = db_session.get(BrandKitVersion, v1_id)
            v1_obj.status = BrandKitVersionStatus.ARCHIVED
            v1_obj.archived_by_user_id = user_id
            v1_obj.archived_at = utcnow()
            db_session.commit()

        # Verify UPDATE on each expired child is rejected without lazy-loading relationship
        for model_cls, cid, attr_name, bad_val in child_specs:
            child_obj = db_session.get(model_cls, cid)
            db_session.expire_all()
            assert "brand_kit_version_id" not in inspect(child_obj).dict
            assert "version" not in inspect(child_obj).dict
            setattr(child_obj, attr_name, bad_val)
            with pytest.raises(IntegrityError) as exc_info:
                db_session.flush()
            assert isinstance(exc_info.value.orig, BrandHubImmutabilityError)
            assert "P0002" in str(exc_info.value.orig)
            assert "version" not in inspect(child_obj).dict
            db_session.rollback()

        # Verify DELETE on each expired child is rejected
        for model_cls, cid, _, _ in child_specs:
            child_obj = db_session.get(model_cls, cid)
            db_session.expire_all()
            db_session.delete(child_obj)
            with pytest.raises(IntegrityError) as exc_info:
                db_session.flush()
            assert isinstance(exc_info.value.orig, BrandHubImmutabilityError)
            assert "P0002" in str(exc_info.value.orig)
            db_session.rollback()

        # Verify INSERT of each of the 6 child models into PUBLISHED/ARCHIVED version is rejected
        doc_id = inspect(children["doc"]).identity[0]
        insert_candidates = [
            BrandIdentity(
                brand_kit_version_id=v1_id,
                organisation_id=org_id,
                brand_name="New Identity on Protected Version",
                tagline="Protected Tagline",
                primary_color_hex="#123456",
            ),
            ApprovedBrandFact(
                brand_kit_version_id=v1_id,
                organisation_id=org_id,
                category=FactCategory.CLAIM_EVIDENCE,
                subject_name="New Claim",
                fact_key="new_claim_key",
                fact_value="100% Organic",
                source_reference="Ref",
            ),
            ComplianceRule(
                brand_kit_version_id=v1_id,
                organisation_id=org_id,
                rule_code="NEW_RULE_PROTECTED",
                rule_type=ComplianceRuleType.PROHIBITED_TERM,
                priority=10,
                severity=RuleSeverity.HIGH,
                title="New Rule on Protected Version",
                description="Prohibited phrase",
                target_pattern="forbidden term",
                source_reference="Policy Ref",
            ),
            BrandAsset(
                brand_kit_version_id=v1_id,
                organisation_id=org_id,
                asset_type=BrandAssetType.ICON,
                title="New Asset on Protected Version",
                original_filename="new_icon.png",
                stored_filename="uuid-new-icon.png",
                storage_path=f"tenants/{org_id}/assets/uuid-new-icon.png",
                mime_type="image/png",
                file_size_bytes=4096,
                file_sha256="1" * 64,
            ),
            BrandGuidelineDocument(
                brand_kit_version_id=v1_id,
                organisation_id=org_id,
                title="New Guideline on Protected Version",
                document_category=GuidelineDocumentCategory.STYLE_GUIDE,
                original_filename="new_guide.pdf",
                stored_filename="uuid-new-guide.pdf",
                storage_path=f"tenants/{org_id}/docs/uuid-new-guide.pdf",
                mime_type="application/pdf",
                file_size_bytes=16384,
                file_sha256="2" * 64,
                parsing_status=DocumentParsingStatus.PENDING,
            ),
            BrandDocumentChunk(
                document_id=doc_id,
                brand_kit_version_id=v1_id,
                organisation_id=org_id,
                chunk_index=99,
                page_number=2,
                char_start=0,
                char_end=20,
                content="New chunk on protected version",
                content_sha256="3" * 64,
                token_count=5,
            ),
        ]
        for new_child in insert_candidates:
            db_session.expire_all()
            db_session.add(new_child)
            with pytest.raises(IntegrityError) as exc_info:
                db_session.flush()
            assert isinstance(exc_info.value.orig, BrandHubImmutabilityError)
            assert "P0002" in str(exc_info.value.orig)
            db_session.rollback()


def test_orm_listener_expired_guideline_document_locked_columns_rejected_and_telemetry_allowed(db_session):
    """Scenario 6 & 7: On an expired BrandGuidelineDocument belonging to a PUBLISHED or ARCHIVED version,
    modifying any of the 14 locked columns is rejected with [P0002], whereas updating all 10 allowlisted
    telemetry columns succeeds.
    """
    user_id, org_id, kit_id = _seed_sqlite_tenant_and_kit(db_session)

    v1 = BrandKitVersion(
        brand_kit_id=kit_id,
        organisation_id=org_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user_id,
    )
    db_session.add(v1)
    db_session.flush()

    doc = BrandGuidelineDocument(
        brand_kit_version_id=v1.id,
        organisation_id=org_id,
        title="Locked Guideline Book",
        document_category=GuidelineDocumentCategory.BRAND_BOOK,
        original_filename="locked.pdf",
        stored_filename="uuid-locked.pdf",
        storage_backend="LOCAL",
        storage_path=f"tenants/{org_id}/docs/uuid-locked.pdf",
        mime_type="application/pdf",
        file_size_bytes=16384,
        file_sha256="d" * 64,
        uploaded_by_user_id=user_id,
        parsing_status=DocumentParsingStatus.PENDING,
    )
    db_session.add(doc)
    db_session.flush()

    v1.status = BrandKitVersionStatus.PUBLISHED
    v1.published_by_user_id = user_id
    v1.published_at = utcnow()
    db_session.commit()
    doc_id = inspect(doc).identity[0]

    locked_mutations = {
        "id": uuid.uuid4(),
        "brand_kit_version_id": uuid.uuid4(),
        "organisation_id": uuid.uuid4(),
        "title": "Tampered Title",
        "document_category": GuidelineDocumentCategory.LEGAL_POLICY,
        "original_filename": "tampered.pdf",
        "stored_filename": "tampered.pdf",
        "storage_backend": "S3",
        "storage_path": "tenants/other/tampered.pdf",
        "mime_type": "text/plain",
        "file_size_bytes": 999,
        "file_sha256": "e" * 64,
        "uploaded_by_user_id": uuid.uuid4(),
        "created_at": utcnow() - timedelta(days=10),
    }
    assert set(locked_mutations.keys()) == LOCKED_GUIDELINE_DOC_COLUMNS

    # Verify all 14 locked columns are rejected when expired
    for col_name, mutated_value in locked_mutations.items():
        doc_obj = db_session.get(BrandGuidelineDocument, doc_id)
        db_session.expire_all()
        assert col_name not in inspect(doc_obj).dict
        setattr(doc_obj, col_name, mutated_value)
        with pytest.raises(IntegrityError) as exc_info:
            db_session.flush()
        assert isinstance(exc_info.value.orig, BrandHubImmutabilityError), f"Locked column {col_name} was not blocked"
        assert "P0002" in str(exc_info.value.orig)
        db_session.rollback()

    # Verify all 10 allowlisted telemetry columns succeed when expired on PUBLISHED version
    now_ts = utcnow()
    doc_obj = db_session.get(BrandGuidelineDocument, doc_id)
    db_session.expire_all()
    doc_obj.parsing_status = DocumentParsingStatus.EMBEDDED
    doc_obj.parse_attempt_count = 2
    doc_obj.last_error_code = "WARN_OCR"
    doc_obj.last_error_message = "Minor OCR warning"
    doc_obj.page_count = 18
    doc_obj.raw_text_content = "Extracted guideline text."
    doc_obj.embedding_model = "BAAI/bge-large-en-v1.5"
    doc_obj.embedding_model_version = "1.5"
    doc_obj.parsed_at = now_ts
    doc_obj.embedded_at = now_ts
    db_session.commit()

    refreshed = db_session.get(BrandGuidelineDocument, doc_id)
    assert refreshed.parsing_status == DocumentParsingStatus.EMBEDDED
    assert refreshed.parse_attempt_count == 2
    assert refreshed.page_count == 18
    assert refreshed.raw_text_content == "Extracted guideline text."
    assert refreshed.title == "Locked Guideline Book"


def test_orm_listener_published_to_archived_transition_allowed_and_snapshot_tampering_rejected(db_session):
    """Scenario 8 & 9: PUBLISHED -> ARCHIVED is rejected with [P0001] if any immutable snapshot column is
    modified (both loaded and expired), and allowed when snapshot columns remain unchanged.
    """
    user_id, org_id, kit_id = _seed_sqlite_tenant_and_kit(db_session)

    ver = BrandKitVersion(
        brand_kit_id=kit_id,
        organisation_id=org_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        changelog="Official Release v1",
        created_by_user_id=user_id,
    )
    db_session.add(ver)
    db_session.flush()

    # Publish through the permitted DRAFT -> PUBLISHED transition.
    ver.status = BrandKitVersionStatus.PUBLISHED
    ver.published_by_user_id = user_id
    ver.published_at = utcnow()
    db_session.commit()
    ver_id = inspect(ver).identity[0]

    snapshot_mutations = [
        ("changelog", "Tampered Changelog"),
        ("cloned_from_version_id", uuid.uuid4()),
        ("created_by_user_id", uuid.uuid4()),
        ("published_by_user_id", uuid.uuid4()),
        ("published_at", utcnow() - timedelta(days=5)),
        ("created_at", utcnow() - timedelta(days=5)),
    ]

    # Scenario 9: Reject PUBLISHED -> ARCHIVED when any snapshot column is tampered while expired
    for col_name, bad_val in snapshot_mutations:
        ver_obj = db_session.get(BrandKitVersion, ver_id)
        db_session.expire_all()
        ver_obj.status = BrandKitVersionStatus.ARCHIVED
        setattr(ver_obj, col_name, bad_val)
        with pytest.raises(IntegrityError) as exc_info:
            db_session.flush()
        assert isinstance(exc_info.value.orig, BrandHubImmutabilityError), f"Snapshot column {col_name} was not locked"
        assert "P0001" in str(exc_info.value.orig)
        db_session.rollback()

    # Scenario 8: Allow PUBLISHED -> ARCHIVED when snapshot columns are untouched (even after expire_all)
    ver_obj = db_session.get(BrandKitVersion, ver_id)
    db_session.expire_all()
    ver_obj.status = BrandKitVersionStatus.ARCHIVED
    ver_obj.archived_by_user_id = user_id
    ver_obj.archived_at = utcnow()
    db_session.commit()

    archived_ver = db_session.get(BrandKitVersion, ver_id)
    assert archived_ver.status == BrandKitVersionStatus.ARCHIVED
    assert archived_ver.changelog == "Official Release v1"


def test_orm_listener_audit_log_append_only_and_org_cascade_allowed(db_session):
    """Scenario 10: BrandAuditLog INSERT is allowed, UPDATE and DELETE are rejected with [P0005]
    (even when expired), and legitimate Organisation cascade deletion is allowed.
    """
    user_id, org_id, kit_id = _seed_sqlite_tenant_and_kit(db_session)

    audit = BrandAuditLog(
        organisation_id=org_id,
        actor_user_id=user_id,
        brand_kit_id=kit_id,
        action="BRAND_KIT_CREATED",
        resource_type=BrandAuditResourceType.BRAND_KIT,
        resource_id=kit_id,
        details_json={"kit": "initial"},
    )
    db_session.add(audit)
    db_session.commit()
    audit_id = inspect(audit).identity[0]

    # 10a. Expired UPDATE on BrandAuditLog is rejected with [P0005]
    audit_obj = db_session.get(BrandAuditLog, audit_id)
    db_session.expire_all()
    audit_obj.action = "TAMPERED_ACTION"
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert isinstance(exc_info.value.orig, BrandHubImmutabilityError)
    assert "P0005" in str(exc_info.value.orig)
    db_session.rollback()

    # 10b. Expired DELETE on BrandAuditLog is rejected with [P0005]
    audit_obj = db_session.get(BrandAuditLog, audit_id)
    db_session.expire_all()
    db_session.delete(audit_obj)
    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()
    assert isinstance(exc_info.value.orig, BrandHubImmutabilityError)
    assert "P0005" in str(exc_info.value.orig)
    db_session.rollback()

    # 10c. Legitimate Organisation deletion cascades cleanly without raising [P0005]
    org_obj = db_session.get(Organisation, org_id)
    db_session.delete(org_obj)
    db_session.commit()
    assert db_session.get(BrandAuditLog, audit_id) is None


def test_orm_listener_ordinary_draft_version_and_child_mutations_allowed(db_session):
    """Scenario 11: Ordinary DRAFT BrandKitVersion and child INSERT, UPDATE, DELETE, and DRAFT deletion remain allowed."""
    user_id, org_id, kit_id = _seed_sqlite_tenant_and_kit(db_session)

    draft_ver = BrandKitVersion(
        brand_kit_id=kit_id,
        organisation_id=org_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        changelog="Initial draft",
        created_by_user_id=user_id,
    )
    db_session.add(draft_ver)
    db_session.flush()

    children = _create_all_six_children(db_session, draft_ver.id, org_id, suffix="draft_ok")
    db_session.commit()

    # Mutate DRAFT version and all 6 children after expire_all()
    db_session.expire_all()
    draft_ver.changelog = "Updated draft changelog"
    children["identity"].brand_name = "Updated Brand Name"
    children["fact"].fact_value = "â‚¹249"
    children["rule"].title = "Updated Rule Title"
    children["asset"].title = "Updated Asset Title"
    children["doc"].title = "Updated Doc Title"
    children["chunk"].content = "Updated chunk content"
    db_session.commit()

    assert draft_ver.changelog == "Updated draft changelog"
    assert children["identity"].brand_name == "Updated Brand Name"

    # Deleting a child from a DRAFT version and deleting the DRAFT version itself is allowed
    db_session.delete(children["chunk"])
    db_session.flush()
    db_session.delete(draft_ver)
    db_session.commit()
    assert db_session.get(BrandKitVersion, draft_ver.id) is None
