"""Phase 2: Secure Organisation Invitations and Lifecycle.

Revision ID: 0002_organisation_invitations
Revises: 0001_phase2_auth_rbac
Create Date: 2026-11-08 14:25:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002_organisation_invitations"
down_revision: Union[str, None] = "0001_phase2_auth_rbac"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organisation_invitations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "organisation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "role_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "invited_by_user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_organisation_invitations_token_hash", "organisation_invitations", ["token_hash"], unique=True)
    op.create_index("ix_organisation_invitations_email", "organisation_invitations", ["email"], unique=False)
    op.create_index("ix_organisation_invitations_organisation_id", "organisation_invitations", ["organisation_id"], unique=False)
    op.create_index("ix_organisation_invitations_role_id", "organisation_invitations", ["role_id"], unique=False)
    op.create_index("ix_organisation_invitations_invited_by_user_id", "organisation_invitations", ["invited_by_user_id"], unique=False)
    op.create_index("ix_organisation_invitations_status", "organisation_invitations", ["status"], unique=False)
    op.create_index("ix_organisation_invitations_expires_at", "organisation_invitations", ["expires_at"], unique=False)
    op.create_index("ix_org_invitations_org_email", "organisation_invitations", ["organisation_id", "email"], unique=False)
    op.create_index("ix_org_invitations_org_status", "organisation_invitations", ["organisation_id", "status"], unique=False)


def downgrade() -> None:
    op.drop_table("organisation_invitations")
