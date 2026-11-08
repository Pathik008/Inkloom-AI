"""Domain service for authentication, user creation, and organisation management."""
import re
import uuid
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import TenantContext
from app.models import (
    MembershipStatus,
    Organisation,
    OrganisationMembership,
    Role,
    User,
)
from app.schemas import (
    CurrentUserResponse,
    OrganisationSummaryResponse,
    UserMembershipContextResponse,
)
from app.services.rbac_service import get_role_permissions, seed_roles_and_permissions


def generate_unique_slug(db: Session, name: str) -> str:
    """Create a URL-safe, unique slug for an organisation."""
    base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not base:
        base = "organisation"
    base = base[:120]
    candidate = base
    counter = 1
    while (
        db.execute(select(Organisation).where(Organisation.slug == candidate)).scalar_one_or_none()
        is not None
    ):
        counter += 1
        candidate = f"{base}-{counter}"
    return candidate


def get_role_by_name(db: Session, role_name: str) -> Role:
    role = db.execute(select(Role).where(Role.name == role_name)).scalar_one_or_none()
    if role is None:
        seed_roles_and_permissions(db)
        role = db.execute(select(Role).where(Role.name == role_name)).scalar_one()
    return role


def count_active_admins(db: Session, organisation_id: uuid.UUID, admin_role_id: uuid.UUID) -> int:
    """Return the number of active ADMIN memberships in an organisation."""
    stmt = (
        select(func.count(OrganisationMembership.id))
        .join(User, User.id == OrganisationMembership.user_id)
        .where(
            OrganisationMembership.organisation_id == organisation_id,
            OrganisationMembership.role_id == admin_role_id,
            OrganisationMembership.status == MembershipStatus.ACTIVE,
            User.is_active.is_(True),
        )
    )
    return int(db.execute(stmt).scalar_one() or 0)


def build_current_user_response(
    db: Session,
    user: User,
    active_context: TenantContext | None = None,
) -> CurrentUserResponse:
    """Construct a CurrentUserResponse including all active organisation memberships and permissions."""
    memberships = (
        db.execute(
            select(OrganisationMembership)
            .where(
                OrganisationMembership.user_id == user.id,
                OrganisationMembership.status == MembershipStatus.ACTIVE,
            )
            .order_by(OrganisationMembership.joined_at.asc())
        )
        .scalars()
        .all()
    )

    membership_items: list[UserMembershipContextResponse] = []
    for m in memberships:
        if m.organisation is None or m.role is None:
            continue
        perms = get_role_permissions(m.role)
        membership_items.append(
            UserMembershipContextResponse(
                membership_id=m.id,
                organisation=OrganisationSummaryResponse.model_validate(m.organisation),
                role=m.role.name,
                permissions=perms,
                status=m.status,
                joined_at=m.joined_at,
            )
        )

    active_org_id: uuid.UUID | None = None
    active_role: str | None = None
    active_permissions: list[str] = []

    if active_context is not None:
        active_org_id = active_context.organisation.id
        active_role = active_context.role_name
        active_permissions = active_context.permissions
    elif membership_items:
        active_org_id = membership_items[0].organisation.id
        active_role = membership_items[0].role
        active_permissions = membership_items[0].permissions

    return CurrentUserResponse(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        is_active=user.is_active,
        is_verified=user.is_verified,
        created_at=user.created_at,
        memberships=membership_items,
        active_organisation_id=active_org_id,
        active_role=active_role,
        active_permissions=active_permissions,
    )
