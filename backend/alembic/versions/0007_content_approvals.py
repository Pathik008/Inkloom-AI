"""Phase 4.2: Human approval workflow and content review audit history.

Revision ID: 0007_content_approvals
Revises: 0006_compliance_workflow
Create Date: 2026-11-09 22:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_content_approvals"
down_revision: Union[str, None] = "0006_compliance_workflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add approval columns to content_submissions
    op.add_column(
        "content_submissions",
        sa.Column("status", sa.String(32), nullable=False, server_default="DRAFT"),
    )
    op.add_column(
        "content_submissions",
        sa.Column(
            "assigned_reviewer_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "content_submissions",
        sa.Column(
            "reviewed_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "content_submissions",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "content_submissions",
        sa.Column("reviewer_comments", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_content_submissions_org_status",
        "content_submissions",
        ["organisation_id", "status"],
    )
    op.create_index(
        "ix_content_submissions_assigned_rev",
        "content_submissions",
        ["assigned_reviewer_id"],
    )

    # 2. Create content_review_actions audit table
    op.create_table(
        "content_review_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "submission_id",
            sa.Uuid(),
            sa.ForeignKey("content_submissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organisation_id",
            sa.Uuid(),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_content_review_actions_sub_created",
        "content_review_actions",
        ["submission_id", "created_at"],
    )
    op.create_index(
        "ix_content_review_actions_org_created",
        "content_review_actions",
        ["organisation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("content_review_actions")
    op.drop_index("ix_content_submissions_assigned_rev", table_name="content_submissions")
    op.drop_index("ix_content_submissions_org_status", table_name="content_submissions")
    op.drop_column("content_submissions", "reviewer_comments")
    op.drop_column("content_submissions", "reviewed_at")
    op.drop_column("content_submissions", "reviewed_by_user_id")
    op.drop_column("content_submissions", "assigned_reviewer_id")
    op.drop_column("content_submissions", "status")
