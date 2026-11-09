"""Phase 4: content submissions and deterministic compliance analyses.

Revision ID: 0006_compliance_workflow
Revises: 0005_guideline_doc_reassignment
Create Date: 2026-11-09 15:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_compliance_workflow"
down_revision: Union[str, None] = "0005_guideline_doc_reassignment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "content_submissions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organisation_id", sa.Uuid(), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("brand_kit_id", sa.Uuid(), sa.ForeignKey("brand_kits.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "brand_kit_version_id",
            sa.Uuid(),
            sa.ForeignKey("brand_kit_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_submission_id",
            sa.Uuid(),
            sa.ForeignKey("content_submissions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("submitted_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision_number >= 1", name="ck_content_submissions_revision"),
    )
    for col in ("organisation_id", "brand_kit_id", "brand_kit_version_id", "parent_submission_id"):
        op.create_index(f"ix_content_submissions_{col}", "content_submissions", [col])
    op.create_index(
        "ix_content_submissions_org_created", "content_submissions", ["organisation_id", "created_at"]
    )

    op.create_table(
        "compliance_analyses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "submission_id", sa.Uuid(), sa.ForeignKey("content_submissions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("organisation_id", sa.Uuid(), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "brand_kit_version_id",
            sa.Uuid(),
            sa.ForeignKey("brand_kit_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("engine_version", sa.String(32), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("result", sa.String(8), nullable=False),
        sa.Column("rules_evaluated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("findings_json", JSONB, nullable=False),
        sa.Column("scoring_json", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("score BETWEEN 0 AND 100", name="ck_compliance_analyses_score"),
        sa.CheckConstraint("result IN ('PASS', 'FAIL')", name="ck_compliance_analyses_result"),
    )
    for col in ("submission_id", "organisation_id", "brand_kit_version_id"):
        op.create_index(f"ix_compliance_analyses_{col}", "compliance_analyses", [col])


def downgrade() -> None:
    op.drop_table("compliance_analyses")
    op.drop_table("content_submissions")
