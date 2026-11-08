"""Phase 2: Users, Organisations, Roles, Permissions, Memberships, and RevokedTokens.

Revision ID: 0001_phase2_auth_rbac
Revises: None
Create Date: 2026-11-08 10:50:00.000000

"""
from typing import Sequence, Union
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

from app.models import (
    PermissionCode,
    ROLE_DESCRIPTIONS,
    ROLE_PERMISSION_MATRIX,
)

# revision identifiers, used by Alembic.
revision: str = "0001_phase2_auth_rbac"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "organisations",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_organisations_slug", "organisations", ["slug"], unique=True)
    op.create_index("ix_organisations_created_by", "organisations", ["created_by"], unique=False)

    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_roles_name", "roles", ["name"], unique=True)

    op.create_table(
        "permissions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_permissions_code", "permissions", ["code"], unique=True)

    op.create_table(
        "role_permissions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "role_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "permission_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("permissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )
    op.create_index("ix_role_permissions_role_id", "role_permissions", ["role_id"], unique=False)
    op.create_index("ix_role_permissions_permission_id", "role_permissions", ["permission_id"], unique=False)

    op.create_table(
        "organisation_memberships",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "organisation_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("roles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "organisation_id", name="uq_user_organisation_membership"),
    )
    op.create_index("ix_organisation_memberships_user_id", "organisation_memberships", ["user_id"], unique=False)
    op.create_index(
        "ix_organisation_memberships_organisation_id", "organisation_memberships", ["organisation_id"], unique=False
    )
    op.create_index("ix_organisation_memberships_role_id", "organisation_memberships", ["role_id"], unique=False)
    op.create_index(
        "ix_org_membership_org_role",
        "organisation_memberships",
        ["organisation_id", "role_id"],
        unique=False,
    )

    op.create_table(
        "revoked_tokens",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("jti", sa.String(length=128), nullable=False),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_revoked_tokens_jti", "revoked_tokens", ["jti"], unique=True)
    op.create_index("ix_revoked_tokens_user_id", "revoked_tokens", ["user_id"], unique=False)

    # Seed predefined roles and permissions inside migration transaction
    now = datetime.now(timezone.utc)
    permissions_table = sa.table(
        "permissions",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("description", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    roles_table = sa.table(
        "roles",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    role_perms_table = sa.table(
        "role_permissions",
        sa.column("id", sa.Uuid(as_uuid=True)),
        sa.column("role_id", sa.Uuid(as_uuid=True)),
        sa.column("permission_id", sa.Uuid(as_uuid=True)),
    )

    perm_ids: dict[str, uuid.UUID] = {}
    perm_rows = []
    for code, desc in PermissionCode.ALL_DESCRIPTIONS.items():
        pid = uuid.uuid4()
        perm_ids[code] = pid
        perm_rows.append({"id": pid, "code": code, "description": desc, "created_at": now})
    op.bulk_insert(permissions_table, perm_rows)

    role_ids: dict[str, uuid.UUID] = {}
    role_rows = []
    for rname, rdesc in ROLE_DESCRIPTIONS.items():
        rid = uuid.uuid4()
        role_ids[rname] = rid
        role_rows.append({"id": rid, "name": rname, "description": rdesc, "created_at": now})
    op.bulk_insert(roles_table, role_rows)

    rp_rows = []
    for rname, codes in ROLE_PERMISSION_MATRIX.items():
        rid = role_ids[rname]
        for code in codes:
            rp_rows.append({"id": uuid.uuid4(), "role_id": rid, "permission_id": perm_ids[code]})
    op.bulk_insert(role_perms_table, rp_rows)


def downgrade() -> None:
    op.drop_index("ix_revoked_tokens_user_id", table_name="revoked_tokens")
    op.drop_index("ix_revoked_tokens_jti", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")

    op.drop_index("ix_org_membership_org_role", table_name="organisation_memberships")
    op.drop_index("ix_organisation_memberships_role_id", table_name="organisation_memberships")
    op.drop_index("ix_organisation_memberships_organisation_id", table_name="organisation_memberships")
    op.drop_index("ix_organisation_memberships_user_id", table_name="organisation_memberships")
    op.drop_table("organisation_memberships")

    op.drop_index("ix_role_permissions_permission_id", table_name="role_permissions")
    op.drop_index("ix_role_permissions_role_id", table_name="role_permissions")
    op.drop_table("role_permissions")

    op.drop_index("ix_permissions_code", table_name="permissions")
    op.drop_table("permissions")

    op.drop_index("ix_roles_name", table_name="roles")
    op.drop_table("roles")

    op.drop_index("ix_organisations_created_by", table_name="organisations")
    op.drop_index("ix_organisations_slug", table_name="organisations")
    op.drop_table("organisations")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
