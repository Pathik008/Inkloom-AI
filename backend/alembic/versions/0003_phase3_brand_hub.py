"""Phase 3: Brand Hub (Versioned Brand Kits, Knowledge Base, Assets, Documents, Chunks & Audit Logs).

Revision ID: 0003_phase3_brand_hub
Revises: 0002_organisation_invitations
Create Date: 2026-11-08 16:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0003_phase3_brand_hub"
down_revision: Union[str, None] = "0002_organisation_invitations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')

        # Idempotent verification of Phase 2 Brand Hub & Audit RBAC permissions and role mappings
        op.execute(
            """
            INSERT INTO permissions (id, code, description, created_at)
            VALUES
                (gen_random_uuid(), 'brand:read', 'View Brand Kits, approved facts, and compliance rules', NOW()),
                (gen_random_uuid(), 'brand:manage', 'Create, update, and publish Brand Kits and rules', NOW()),
                (gen_random_uuid(), 'audit:read', 'View organisation security and compliance audit logs', NOW())
            ON CONFLICT (code) DO NOTHING;
            """
        )
        op.execute(
            """
            INSERT INTO role_permissions (id, role_id, permission_id)
            SELECT gen_random_uuid(), r.id, p.id
            FROM roles r
            JOIN permissions p ON p.code = 'brand:read'
            WHERE r.name IN ('ADMIN', 'BRAND_MANAGER', 'CONTENT_CREATOR', 'REVIEWER')
            ON CONFLICT (role_id, permission_id) DO NOTHING;
            """
        )
        op.execute(
            """
            INSERT INTO role_permissions (id, role_id, permission_id)
            SELECT gen_random_uuid(), r.id, p.id
            FROM roles r
            JOIN permissions p ON p.code = 'brand:manage'
            WHERE r.name IN ('ADMIN', 'BRAND_MANAGER')
            ON CONFLICT (role_id, permission_id) DO NOTHING;
            """
        )
        op.execute(
            """
            INSERT INTO role_permissions (id, role_id, permission_id)
            SELECT gen_random_uuid(), r.id, p.id
            FROM roles r
            JOIN permissions p ON p.code = 'audit:read'
            WHERE r.name = 'ADMIN'
            ON CONFLICT (role_id, permission_id) DO NOTHING;
            """
        )

    # 1. Table: brand_kits
    op.create_table(
        "brand_kits",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organisation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("active_version_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "organisation_id", name="uq_brand_kits_id_org"),
        sa.UniqueConstraint("organisation_id", "slug", name="uq_brand_kits_org_slug"),
    )
    op.create_index("ix_brand_kits_organisation_id", "brand_kits", ["organisation_id"], unique=False)
    op.create_index("ix_brand_kits_active_version_id", "brand_kits", ["active_version_id"], unique=False)
    op.create_index("ix_brand_kits_created_by_user_id", "brand_kits", ["created_by_user_id"], unique=False)
    op.create_index(
        "ix_brand_kits_org_archived",
        "brand_kits",
        ["organisation_id", "is_archived"],
        unique=False,
    )

    # 2. Table: brand_kit_versions
    op.create_table(
        "brand_kit_versions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("brand_kit_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "organisation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="DRAFT"),
        sa.Column("changelog", sa.Text(), nullable=True),
        sa.Column(
            "cloned_from_version_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("brand_kit_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "published_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "archived_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["brand_kit_id", "organisation_id"],
            ["brand_kits.id", "brand_kits.organisation_id"],
            name="fk_brand_kit_versions_kit_org",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "organisation_id", name="uq_brand_kit_versions_id_org"),
        sa.UniqueConstraint("id", "brand_kit_id", "organisation_id", name="uq_brand_kit_versions_id_kit_org"),
        sa.UniqueConstraint("brand_kit_id", "version_number", name="uq_brand_kit_version_number"),
        sa.CheckConstraint("version_number >= 1", name="ck_brand_kit_versions_version_number_pos"),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PUBLISHED', 'ARCHIVED')",
            name="ck_brand_kit_versions_status",
        ),
    )
    op.create_index("ix_brand_kit_versions_brand_kit_id", "brand_kit_versions", ["brand_kit_id"], unique=False)
    op.create_index("ix_brand_kit_versions_organisation_id", "brand_kit_versions", ["organisation_id"], unique=False)
    op.create_index("ix_brand_kit_versions_status", "brand_kit_versions", ["status"], unique=False)
    op.create_index(
        "ix_brand_kit_versions_created_by_user_id",
        "brand_kit_versions",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        "uq_brand_kit_single_draft",
        "brand_kit_versions",
        ["brand_kit_id"],
        unique=True,
        postgresql_where=sa.text("status = 'DRAFT'"),
        sqlite_where=sa.text("status = 'DRAFT'"),
    )
    op.create_index(
        "ix_brand_kit_versions_org_kit_status",
        "brand_kit_versions",
        ["organisation_id", "brand_kit_id", "status"],
        unique=False,
    )

    # Link brand_kits.active_version_id -> brand_kit_versions.id
    op.create_foreign_key(
        "fk_brand_kits_active_version_id",
        "brand_kits",
        "brand_kit_versions",
        ["active_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 3. Table: brand_identities
    op.create_table(
        "brand_identities",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("brand_kit_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "organisation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("brand_name", sa.String(length=150), nullable=False),
        sa.Column("tagline", sa.String(length=255), nullable=True),
        sa.Column("mission_statement", sa.Text(), nullable=True),
        sa.Column("brand_voice_tone", sa.String(length=255), nullable=True),
        sa.Column("brand_voice_guidelines", sa.Text(), nullable=True),
        sa.Column(
            "preferred_vocabulary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "prohibited_vocabulary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "color_palette_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "typography_rules_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("primary_color_hex", sa.String(length=7), nullable=True),
        sa.Column("secondary_color_hex", sa.String(length=7), nullable=True),
        sa.Column("accent_color_hex", sa.String(length=7), nullable=True),
        sa.Column("neutral_light_hex", sa.String(length=7), nullable=True),
        sa.Column("neutral_dark_hex", sa.String(length=7), nullable=True),
        sa.Column("primary_font_family", sa.String(length=120), nullable=True),
        sa.Column("secondary_font_family", sa.String(length=120), nullable=True),
        sa.Column(
            "updated_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["brand_kit_version_id", "organisation_id"],
            ["brand_kit_versions.id", "brand_kit_versions.organisation_id"],
            name="fk_brand_identities_version_org",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("brand_kit_version_id", name="uq_brand_identities_version"),
    )
    op.create_index("ix_brand_identities_organisation_id", "brand_identities", ["organisation_id"], unique=False)

    # 4. Table: brand_guideline_documents (created before facts & rules that reference it)
    op.create_table(
        "brand_guideline_documents",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("brand_kit_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "organisation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("document_category", sa.String(length=64), nullable=False, server_default="STYLE_GUIDE"),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_backend", sa.String(length=32), nullable=False, server_default="LOCAL"),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("parsing_status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("parse_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("raw_text_content", sa.Text(), nullable=True),
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
        sa.Column("embedding_model_version", sa.String(length=64), nullable=True),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "uploaded_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["brand_kit_version_id", "organisation_id"],
            ["brand_kit_versions.id", "brand_kit_versions.organisation_id"],
            name="fk_brand_guideline_docs_version_org",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "id",
            "brand_kit_version_id",
            "organisation_id",
            name="uq_brand_guideline_docs_id_ver_org",
        ),
        sa.CheckConstraint(
            "file_size_bytes > 0 AND file_size_bytes <= 26214400",
            name="ck_brand_guideline_docs_file_size",
        ),
        sa.CheckConstraint("parse_attempt_count >= 0", name="ck_brand_guideline_docs_attempt_count"),
        sa.CheckConstraint(
            "parsing_status IN ('PENDING', 'PROCESSING', 'PARSED', 'COMPLETED', 'EMBEDDED', 'FAILED')",
            name="ck_brand_guideline_docs_parsing_status",
        ),
    )
    op.create_index(
        "ix_brand_guideline_documents_brand_kit_version_id",
        "brand_guideline_documents",
        ["brand_kit_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_brand_guideline_documents_organisation_id",
        "brand_guideline_documents",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_brand_guideline_documents_file_sha256",
        "brand_guideline_documents",
        ["file_sha256"],
        unique=False,
    )
    op.create_index(
        "ix_brand_guideline_documents_parsing_status",
        "brand_guideline_documents",
        ["parsing_status"],
        unique=False,
    )
    op.create_index(
        "ix_brand_guideline_docs_org_ver_status",
        "brand_guideline_documents",
        ["organisation_id", "brand_kit_version_id", "parsing_status"],
        unique=False,
    )

    # 5. Table: approved_brand_facts
    op.create_table(
        "approved_brand_facts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("brand_kit_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "organisation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("subject_name", sa.String(length=150), nullable=False),
        sa.Column("fact_key", sa.String(length=150), nullable=False),
        sa.Column("fact_value", sa.Text(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("numeric_value", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="MANUAL_ENTRY"),
        sa.Column(
            "source_document_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("brand_guideline_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_reference", sa.String(length=500), nullable=False),
        sa.Column("evidence_excerpt", sa.Text(), nullable=True),
        sa.Column("approval_status", sa.String(length=32), nullable=False, server_default="PENDING_REVIEW"),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["brand_kit_version_id", "organisation_id"],
            ["brand_kit_versions.id", "brand_kit_versions.organisation_id"],
            name="fk_approved_brand_facts_version_org",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("brand_kit_version_id", "fact_key", name="uq_approved_brand_facts_version_key"),
        sa.CheckConstraint(
            "approval_status IN ('PENDING_REVIEW', 'APPROVED', 'REJECTED')",
            name="ck_approved_brand_facts_approval_status",
        ),
        sa.CheckConstraint(
            "source_type IN ('MANUAL_ENTRY', 'GUIDELINE_DOCUMENT', 'EXTERNAL_REGULATION', 'AI_EXTRACTED')",
            name="ck_approved_brand_facts_source_type",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="ck_approved_brand_facts_effective_dates",
        ),
    )
    op.create_index(
        "ix_approved_brand_facts_brand_kit_version_id",
        "approved_brand_facts",
        ["brand_kit_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_approved_brand_facts_organisation_id",
        "approved_brand_facts",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_approved_brand_facts_source_document_id",
        "approved_brand_facts",
        ["source_document_id"],
        unique=False,
    )
    op.create_index(
        "ix_approved_brand_facts_approval_status",
        "approved_brand_facts",
        ["approval_status"],
        unique=False,
    )
    op.create_index(
        "ix_approved_brand_facts_org_ver_cat",
        "approved_brand_facts",
        ["organisation_id", "brand_kit_version_id", "category"],
        unique=False,
    )

    # 6. Table: compliance_rules
    op.create_table(
        "compliance_rules",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("brand_kit_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "organisation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rule_code", sa.String(length=64), nullable=False),
        sa.Column("rule_type", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("severity", sa.String(length=32), nullable=False, server_default="HIGH"),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("target_pattern", sa.Text(), nullable=False),
        sa.Column("match_mode", sa.String(length=32), nullable=False, server_default="CASE_INSENSITIVE"),
        sa.Column("required_disclaimer_text", sa.Text(), nullable=True),
        sa.Column("suggested_replacement", sa.Text(), nullable=True),
        sa.Column(
            "rule_config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="MANUAL_ENTRY"),
        sa.Column(
            "source_document_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("brand_guideline_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_reference", sa.String(length=500), nullable=False),
        sa.Column("evidence_excerpt", sa.Text(), nullable=True),
        sa.Column("approval_status", sa.String(length=32), nullable=False, server_default="PENDING_REVIEW"),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["brand_kit_version_id", "organisation_id"],
            ["brand_kit_versions.id", "brand_kit_versions.organisation_id"],
            name="fk_compliance_rules_version_org",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("brand_kit_version_id", "rule_code", name="uq_compliance_rules_version_code"),
        sa.CheckConstraint("priority BETWEEN 1 AND 1000", name="ck_compliance_rules_priority_range"),
        sa.CheckConstraint(
            "severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO')",
            name="ck_compliance_rules_severity",
        ),
        sa.CheckConstraint(
            "approval_status IN ('PENDING_REVIEW', 'APPROVED', 'REJECTED')",
            name="ck_compliance_rules_approval_status",
        ),
        sa.CheckConstraint(
            "source_type IN ('MANUAL_ENTRY', 'GUIDELINE_DOCUMENT', 'EXTERNAL_REGULATION', 'AI_EXTRACTED')",
            name="ck_compliance_rules_source_type",
        ),
        sa.CheckConstraint(
            "match_mode IN ('EXACT', 'CASE_INSENSITIVE', 'WORD_BOUNDARY', 'REGEX')",
            name="ck_compliance_rules_match_mode",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="ck_compliance_rules_effective_dates",
        ),
    )
    op.create_index(
        "ix_compliance_rules_brand_kit_version_id",
        "compliance_rules",
        ["brand_kit_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_compliance_rules_organisation_id",
        "compliance_rules",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_compliance_rules_source_document_id",
        "compliance_rules",
        ["source_document_id"],
        unique=False,
    )
    op.create_index(
        "ix_compliance_rules_approval_status",
        "compliance_rules",
        ["approval_status"],
        unique=False,
    )
    op.create_index(
        "ix_compliance_rules_org_ver_type",
        "compliance_rules",
        ["organisation_id", "brand_kit_version_id", "rule_type"],
        unique=False,
    )

    # 7. Table: brand_assets
    op.create_table(
        "brand_assets",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("brand_kit_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "organisation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_backend", sa.String(length=32), nullable=False, server_default="LOCAL"),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("image_width", sa.Integer(), nullable=True),
        sa.Column("image_height", sa.Integer(), nullable=True),
        sa.Column(
            "asset_metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "uploaded_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["brand_kit_version_id", "organisation_id"],
            ["brand_kit_versions.id", "brand_kit_versions.organisation_id"],
            name="fk_brand_assets_version_org",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "file_size_bytes > 0 AND file_size_bytes <= 10485760",
            name="ck_brand_assets_file_size",
        ),
    )
    op.create_index("ix_brand_assets_brand_kit_version_id", "brand_assets", ["brand_kit_version_id"], unique=False)
    op.create_index("ix_brand_assets_organisation_id", "brand_assets", ["organisation_id"], unique=False)
    op.create_index("ix_brand_assets_file_sha256", "brand_assets", ["file_sha256"], unique=False)
    op.create_index(
        "ix_brand_assets_org_ver_type",
        "brand_assets",
        ["organisation_id", "brand_kit_version_id", "asset_type"],
        unique=False,
    )

    # 8. Table: brand_document_chunks
    op.create_table(
        "brand_document_chunks",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("brand_kit_version_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "organisation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_heading", sa.String(length=255), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column(
            "embedding_model",
            sa.String(length=120),
            nullable=False,
            server_default="BAAI/bge-large-en-v1.5",
        ),
        sa.Column("embedding_model_version", sa.String(length=64), nullable=False, server_default="1.5"),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False, server_default="1024"),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id", "brand_kit_version_id", "organisation_id"],
            [
                "brand_guideline_documents.id",
                "brand_guideline_documents.brand_kit_version_id",
                "brand_guideline_documents.organisation_id",
            ],
            name="fk_brand_doc_chunks_doc_ver_org",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_brand_doc_chunks_doc_index"),
        sa.CheckConstraint("chunk_index >= 0", name="ck_brand_doc_chunks_index_nonneg"),
        sa.CheckConstraint(
            "char_end >= char_start AND char_start >= 0",
            name="ck_brand_doc_chunks_char_bounds",
        ),
        sa.CheckConstraint("token_count > 0", name="ck_brand_doc_chunks_token_count_pos"),
        sa.CheckConstraint("embedding_dimension = 1024", name="ck_brand_doc_chunks_embedding_dim"),
    )
    op.create_index(
        "ix_brand_document_chunks_document_id",
        "brand_document_chunks",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        "ix_brand_document_chunks_brand_kit_version_id",
        "brand_document_chunks",
        ["brand_kit_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_brand_document_chunks_organisation_id",
        "brand_document_chunks",
        ["organisation_id"],
        unique=False,
    )
    op.create_index(
        "ix_brand_document_chunks_content_sha256",
        "brand_document_chunks",
        ["content_sha256"],
        unique=False,
    )
    op.create_index(
        "ix_brand_doc_chunks_org_ver_doc",
        "brand_document_chunks",
        ["organisation_id", "brand_kit_version_id", "document_id"],
        unique=False,
    )

    # 9. Table: brand_audit_logs
    op.create_table(
        "brand_audit_logs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organisation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "brand_kit_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("brand_kits.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "brand_kit_version_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("brand_kit_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_brand_audit_logs_organisation_id", "brand_audit_logs", ["organisation_id"], unique=False)
    op.create_index("ix_brand_audit_logs_actor_user_id", "brand_audit_logs", ["actor_user_id"], unique=False)
    op.create_index("ix_brand_audit_logs_brand_kit_id", "brand_audit_logs", ["brand_kit_id"], unique=False)
    op.create_index(
        "ix_brand_audit_logs_brand_kit_version_id",
        "brand_audit_logs",
        ["brand_kit_version_id"],
        unique=False,
    )
    op.create_index("ix_brand_audit_logs_action", "brand_audit_logs", ["action"], unique=False)
    op.create_index("ix_brand_audit_logs_created_at", "brand_audit_logs", ["created_at"], unique=False)
    op.create_index(
        "ix_brand_audit_logs_org_kit_created",
        "brand_audit_logs",
        ["organisation_id", "brand_kit_id", "created_at"],
        unique=False,
    )

    # Install PostgreSQL triggers for tenant integrity, lifecycle transitions, and published/archived immutability
    if bind.dialect.name == "postgresql":
        # Trigger Function 1: Validate brand_kits.active_version_id belongs to same kit & org and is PUBLISHED
        op.execute(
            """
            CREATE OR REPLACE FUNCTION fn_validate_brand_kit_active_version()
            RETURNS TRIGGER AS $$
            DECLARE
                v_status VARCHAR(32);
                v_kit_id UUID;
                v_org_id UUID;
            BEGIN
                IF NEW.active_version_id IS NOT NULL THEN
                    SELECT status, brand_kit_id, organisation_id
                    INTO v_status, v_kit_id, v_org_id
                    FROM brand_kit_versions
                    WHERE id = NEW.active_version_id;

                    IF NOT FOUND THEN
                        RAISE EXCEPTION '[P0004] active_version_id (%) does not exist in brand_kit_versions.',
                            NEW.active_version_id
                            USING ERRCODE = '23503';
                    END IF;

                    IF v_kit_id IS DISTINCT FROM NEW.id OR v_org_id IS DISTINCT FROM NEW.organisation_id THEN
                        RAISE EXCEPTION '[P0004] Cross-tenant or cross-kit active_version_id (%) rejected for brand_kit (id=%, org=%).',
                            NEW.active_version_id, NEW.id, NEW.organisation_id
                            USING ERRCODE = '23514';
                    END IF;

                    IF v_status <> 'PUBLISHED' THEN
                        RAISE EXCEPTION '[P0003] active_version_id (%) must have status PUBLISHED (current status=%).',
                            NEW.active_version_id, v_status
                            USING ERRCODE = '23514';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_validate_brand_kit_active_version
            BEFORE INSERT OR UPDATE OF active_version_id, organisation_id ON brand_kits
            FOR EACH ROW EXECUTE FUNCTION fn_validate_brand_kit_active_version();
            """
        )

        # Trigger Function 2: Enforce brand_kit_versions lifecycle & immutability
        op.execute(
            """
            CREATE OR REPLACE FUNCTION fn_enforce_brand_kit_version_immutability()
            RETURNS TRIGGER AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    IF OLD.status IN ('PUBLISHED', 'ARCHIVED') AND EXISTS (
                        SELECT 1 FROM organisations WHERE id = OLD.organisation_id
                    ) THEN
                        RAISE EXCEPTION '[P0001] Cannot delete a % BrandKitVersion (id=%). Published and archived versions are immutable.',
                            OLD.status, OLD.id
                            USING ERRCODE = '23514';
                    END IF;
                    RETURN OLD;
                END IF;

                IF TG_OP = 'UPDATE' THEN
                    -- Prevent changing immutable structural ownership columns on any version
                    IF (
                        NEW.id IS DISTINCT FROM OLD.id OR
                        NEW.brand_kit_id IS DISTINCT FROM OLD.brand_kit_id OR
                        NEW.organisation_id IS DISTINCT FROM OLD.organisation_id OR
                        NEW.version_number IS DISTINCT FROM OLD.version_number
                    ) THEN
                        RAISE EXCEPTION '[P0001] Cannot modify structural identity columns (id, brand_kit_id, organisation_id, version_number) of BrandKitVersion (id=%).',
                            OLD.id
                            USING ERRCODE = '23514';
                    END IF;

                    -- 1. From DRAFT: only DRAFT or PUBLISHED is permitted (DRAFT -> ARCHIVED is forbidden)
                    IF OLD.status = 'DRAFT' THEN
                        IF NEW.status = 'ARCHIVED' THEN
                            RAISE EXCEPTION '[P0003] Invalid status transition from DRAFT to ARCHIVED for BrandKitVersion (id=%). A draft must be published before archiving.',
                                OLD.id
                                USING ERRCODE = '23514';
                        END IF;
                        IF NEW.status = 'PUBLISHED' AND NEW.published_at IS NULL THEN
                            NEW.published_at := NOW();
                        END IF;
                        RETURN NEW;
                    END IF;

                    -- 2. From ARCHIVED: terminal state, zero modifications allowed
                    IF OLD.status = 'ARCHIVED' THEN
                        RAISE EXCEPTION '[P0003] BrandKitVersion (id=%) is ARCHIVED (terminal state) and cannot be modified or restored to %.',
                            OLD.id, NEW.status
                            USING ERRCODE = '23514';
                    END IF;

                    -- 3. From PUBLISHED: only transition to ARCHIVED is permitted, with all snapshot fields locked
                    IF OLD.status = 'PUBLISHED' THEN
                        IF NEW.status <> 'ARCHIVED' THEN
                            RAISE EXCEPTION '[P0001] Cannot modify a PUBLISHED BrandKitVersion (id=%). Only transition to ARCHIVED is permitted.',
                                OLD.id
                                USING ERRCODE = '23514';
                        END IF;

                        IF (
                            NEW.changelog IS DISTINCT FROM OLD.changelog OR
                            NEW.cloned_from_version_id IS DISTINCT FROM OLD.cloned_from_version_id OR
                            NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id OR
                            NEW.published_by_user_id IS DISTINCT FROM OLD.published_by_user_id OR
                            NEW.published_at IS DISTINCT FROM OLD.published_at OR
                            NEW.created_at IS DISTINCT FROM OLD.created_at
                        ) THEN
                            RAISE EXCEPTION '[P0001] Cannot modify immutable snapshot columns of PUBLISHED BrandKitVersion (id=%) during archive transition.',
                                OLD.id
                                USING ERRCODE = '23514';
                        END IF;

                        IF NEW.archived_at IS NULL THEN
                            NEW.archived_at := NOW();
                        END IF;

                        -- Automatically clear active_version_id on parent BrandKit if this version was active
                        UPDATE brand_kits
                        SET active_version_id = NULL, updated_at = NOW()
                        WHERE id = NEW.brand_kit_id AND active_version_id = NEW.id;

                        RETURN NEW;
                    END IF;
                END IF;

                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_enforce_brand_kit_version_immutability
            BEFORE UPDATE OR DELETE ON brand_kit_versions
            FOR EACH ROW EXECUTE FUNCTION fn_enforce_brand_kit_version_immutability();
            """
        )

        # Trigger Function 3: Enforce child table immutability and cross-tenant source_document_id integrity
        op.execute(
            """
            CREATE OR REPLACE FUNCTION fn_enforce_brand_version_child_immutability()
            RETURNS TRIGGER AS $$
            DECLARE
                parent_status VARCHAR(32);
                old_parent_status VARCHAR(32);
                target_version_id UUID;
                target_org_id UUID;
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    target_version_id := OLD.brand_kit_version_id;
                    target_org_id := OLD.organisation_id;
                ELSE
                    target_version_id := NEW.brand_kit_version_id;
                    target_org_id := NEW.organisation_id;
                END IF;

                IF TG_OP = 'UPDATE' AND NEW.brand_kit_version_id IS DISTINCT FROM OLD.brand_kit_version_id THEN
                    SELECT status INTO old_parent_status
                    FROM brand_kit_versions
                    WHERE id = OLD.brand_kit_version_id;

                    IF old_parent_status IS NOT NULL AND old_parent_status IN ('PUBLISHED', 'ARCHIVED') THEN
                        RAISE EXCEPTION '[P0002] Cannot move child record out of % BrandKitVersion (id=%).',
                            old_parent_status, OLD.brand_kit_version_id
                            USING ERRCODE = '23514';
                    END IF;
                END IF;

                SELECT status INTO parent_status
                FROM brand_kit_versions
                WHERE id = target_version_id;

                IF parent_status IS NOT NULL AND parent_status IN ('PUBLISHED', 'ARCHIVED') THEN
                    IF TG_OP = 'DELETE' AND NOT EXISTS (
                        SELECT 1 FROM organisations WHERE id = target_org_id
                    ) THEN
                        RETURN OLD;
                    END IF;

                    RAISE EXCEPTION '[P0002] Cannot % child record in % because parent BrandKitVersion (id=%) is % and immutable.',
                        TG_OP, TG_TABLE_NAME, target_version_id, parent_status
                        USING ERRCODE = '23514';
                END IF;

                -- Validate source_document_id tenant and version consistency on facts and rules
                IF TG_OP IN ('INSERT', 'UPDATE') AND TG_TABLE_NAME IN ('approved_brand_facts', 'compliance_rules') THEN
                    IF NEW.source_document_id IS NOT NULL THEN
                        PERFORM 1
                        FROM brand_guideline_documents
                        WHERE id = NEW.source_document_id
                          AND brand_kit_version_id = NEW.brand_kit_version_id
                          AND organisation_id = NEW.organisation_id;

                        IF NOT FOUND THEN
                            RAISE EXCEPTION '[P0004] source_document_id (%) in % must belong to the same brand_kit_version_id (%) and organisation_id (%).',
                                NEW.source_document_id, TG_TABLE_NAME, NEW.brand_kit_version_id, NEW.organisation_id
                                USING ERRCODE = '23503';
                        END IF;
                    END IF;
                END IF;

                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )

        for child_table in (
            "brand_identities",
            "approved_brand_facts",
            "compliance_rules",
            "brand_assets",
            "brand_document_chunks",
        ):
            op.execute(
                f"""
                CREATE TRIGGER trg_enforce_{child_table}_immutability
                BEFORE INSERT OR UPDATE OR DELETE ON {child_table}
                FOR EACH ROW EXECUTE FUNCTION fn_enforce_brand_version_child_immutability();
                """
            )

        # Trigger Function 4: Enforce brand_guideline_documents immutability with processing telemetry allowlist
        op.execute(
            """
            CREATE OR REPLACE FUNCTION fn_enforce_guideline_doc_immutability()
            RETURNS TRIGGER AS $$
            DECLARE
                parent_status VARCHAR(32);
                target_version_id UUID;
                target_org_id UUID;
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    target_version_id := OLD.brand_kit_version_id;
                    target_org_id := OLD.organisation_id;
                ELSE
                    target_version_id := NEW.brand_kit_version_id;
                    target_org_id := NEW.organisation_id;
                END IF;

                SELECT status INTO parent_status
                FROM brand_kit_versions
                WHERE id = target_version_id;

                IF parent_status IS NOT NULL AND parent_status IN ('PUBLISHED', 'ARCHIVED') THEN
                    IF TG_OP = 'DELETE' THEN
                        IF NOT EXISTS (SELECT 1 FROM organisations WHERE id = target_org_id) THEN
                            RETURN OLD;
                        END IF;
                        RAISE EXCEPTION '[P0002] Cannot DELETE brand_guideline_documents belonging to a % BrandKitVersion (id=%).',
                            parent_status, target_version_id
                            USING ERRCODE = '23514';
                    END IF;

                    IF TG_OP = 'INSERT' THEN
                        RAISE EXCEPTION '[P0002] Cannot INSERT brand_guideline_documents into a % BrandKitVersion (id=%).',
                            parent_status, target_version_id
                            USING ERRCODE = '23514';
                    END IF;

                    IF TG_OP = 'UPDATE' THEN
                        -- Strictly lock all 14 file identity, ownership, version association, and provenance columns.
                        -- Only the 10 allowlisted processing telemetry columns may be updated after publication:
                        -- (parsing_status, parse_attempt_count, last_error_code, last_error_message,
                        --  page_count, raw_text_content, embedding_model, embedding_model_version, parsed_at, embedded_at)
                        IF (
                            NEW.id IS DISTINCT FROM OLD.id OR
                            NEW.brand_kit_version_id IS DISTINCT FROM OLD.brand_kit_version_id OR
                            NEW.organisation_id IS DISTINCT FROM OLD.organisation_id OR
                            NEW.title IS DISTINCT FROM OLD.title OR
                            NEW.document_category IS DISTINCT FROM OLD.document_category OR
                            NEW.original_filename IS DISTINCT FROM OLD.original_filename OR
                            NEW.stored_filename IS DISTINCT FROM OLD.stored_filename OR
                            NEW.storage_backend IS DISTINCT FROM OLD.storage_backend OR
                            NEW.storage_path IS DISTINCT FROM OLD.storage_path OR
                            NEW.mime_type IS DISTINCT FROM OLD.mime_type OR
                            NEW.file_size_bytes IS DISTINCT FROM OLD.file_size_bytes OR
                            NEW.file_sha256 IS DISTINCT FROM OLD.file_sha256 OR
                            NEW.uploaded_by_user_id IS DISTINCT FROM OLD.uploaded_by_user_id OR
                            NEW.created_at IS DISTINCT FROM OLD.created_at
                        ) THEN
                            RAISE EXCEPTION '[P0002] Cannot modify immutable file identity, ownership, or provenance columns on brand_guideline_documents for % BrandKitVersion (id=%).',
                                parent_status, target_version_id
                                USING ERRCODE = '23514';
                        END IF;
                    END IF;
                END IF;

                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_enforce_guideline_doc_immutability
            BEFORE INSERT OR UPDATE OR DELETE ON brand_guideline_documents
            FOR EACH ROW EXECUTE FUNCTION fn_enforce_guideline_doc_immutability();
            """
        )

        # Trigger Function 5: Validate tenant consistency and append-only protection on brand_audit_logs
        op.execute(
            """
            CREATE OR REPLACE FUNCTION fn_validate_and_protect_brand_audit_logs()
            RETURNS TRIGGER AS $$
            BEGIN
                IF TG_OP = 'INSERT' THEN
                    IF NEW.brand_kit_id IS NOT NULL THEN
                        PERFORM 1 FROM brand_kits
                        WHERE id = NEW.brand_kit_id AND organisation_id = NEW.organisation_id;
                        IF NOT FOUND THEN
                            RAISE EXCEPTION '[P0004] Cross-tenant brand_kit_id (%) rejected on brand_audit_logs for organisation_id (%).',
                                NEW.brand_kit_id, NEW.organisation_id
                                USING ERRCODE = '23503';
                        END IF;
                    END IF;

                    IF NEW.brand_kit_version_id IS NOT NULL THEN
                        PERFORM 1 FROM brand_kit_versions
                        WHERE id = NEW.brand_kit_version_id
                          AND organisation_id = NEW.organisation_id
                          AND (NEW.brand_kit_id IS NULL OR brand_kit_id = NEW.brand_kit_id);
                        IF NOT FOUND THEN
                            RAISE EXCEPTION '[P0004] Cross-tenant or mismatched brand_kit_version_id (%) rejected on brand_audit_logs for organisation_id (%).',
                                NEW.brand_kit_version_id, NEW.organisation_id
                                USING ERRCODE = '23503';
                        END IF;
                    END IF;

                    RETURN NEW;
                END IF;

                IF TG_OP = 'DELETE' THEN
                    IF EXISTS (SELECT 1 FROM organisations WHERE id = OLD.organisation_id) THEN
                        RAISE EXCEPTION '[P0005] brand_audit_logs are append-only and cannot be deleted (id=%).',
                            OLD.id
                            USING ERRCODE = '23514';
                    END IF;
                    RETURN OLD;
                END IF;

                IF TG_OP = 'UPDATE' THEN
                    -- Permit only FK ON DELETE SET NULL cascade when a DRAFT version or kit is deleted
                    IF (
                        NEW.id IS NOT DISTINCT FROM OLD.id AND
                        NEW.organisation_id IS NOT DISTINCT FROM OLD.organisation_id AND
                        NEW.actor_user_id IS NOT DISTINCT FROM OLD.actor_user_id AND
                        NEW.action IS NOT DISTINCT FROM OLD.action AND
                        NEW.resource_type IS NOT DISTINCT FROM OLD.resource_type AND
                        NEW.resource_id IS NOT DISTINCT FROM OLD.resource_id AND
                        NEW.details_json IS NOT DISTINCT FROM OLD.details_json AND
                        NEW.created_at IS NOT DISTINCT FROM OLD.created_at AND
                        (NEW.brand_kit_id IS NULL OR NEW.brand_kit_id IS NOT DISTINCT FROM OLD.brand_kit_id) AND
                        (NEW.brand_kit_version_id IS NULL OR NEW.brand_kit_version_id IS NOT DISTINCT FROM OLD.brand_kit_version_id)
                    ) THEN
                        RETURN NEW;
                    END IF;

                    RAISE EXCEPTION '[P0005] brand_audit_logs are append-only and cannot be modified (id=%).',
                        OLD.id
                        USING ERRCODE = '23514';
                END IF;

                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_validate_and_protect_brand_audit_logs
            BEFORE INSERT OR UPDATE OR DELETE ON brand_audit_logs
            FOR EACH ROW EXECUTE FUNCTION fn_validate_and_protect_brand_audit_logs();
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_validate_and_protect_brand_audit_logs ON brand_audit_logs;")
        op.execute("DROP TRIGGER IF EXISTS trg_enforce_guideline_doc_immutability ON brand_guideline_documents;")
        for child_table in (
            "brand_document_chunks",
            "brand_assets",
            "compliance_rules",
            "approved_brand_facts",
            "brand_identities",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS trg_enforce_{child_table}_immutability ON {child_table};")
        op.execute("DROP TRIGGER IF EXISTS trg_enforce_brand_kit_version_immutability ON brand_kit_versions;")
        op.execute("DROP TRIGGER IF EXISTS trg_validate_brand_kit_active_version ON brand_kits;")

        op.execute("DROP FUNCTION IF EXISTS fn_validate_and_protect_brand_audit_logs();")
        op.execute("DROP FUNCTION IF EXISTS fn_enforce_guideline_doc_immutability();")
        op.execute("DROP FUNCTION IF EXISTS fn_enforce_brand_version_child_immutability();")
        op.execute("DROP FUNCTION IF EXISTS fn_enforce_brand_kit_version_immutability();")
        op.execute("DROP FUNCTION IF EXISTS fn_validate_brand_kit_active_version();")

    op.drop_table("brand_audit_logs")
    op.drop_table("brand_document_chunks")
    op.drop_table("brand_assets")
    op.drop_table("compliance_rules")
    op.drop_table("approved_brand_facts")
    op.drop_table("brand_guideline_documents")
    op.drop_table("brand_identities")
    op.drop_constraint("fk_brand_kits_active_version_id", "brand_kits", type_="foreignkey")
    op.drop_table("brand_kit_versions")
    op.drop_table("brand_kits")
