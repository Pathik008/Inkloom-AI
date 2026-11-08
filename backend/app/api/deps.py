"""Reusable FastAPI dependencies for authentication, tenant isolation, and RBAC."""
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import Depends, Header, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database import get_db
from app.models import (
    MembershipStatus,
    Organisation,
    OrganisationMembership,
    RevokedToken,
    User,
)
from app.services.rbac_service import get_role_permissions

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class AuthenticatedPrincipal:
    user: User
    token_payload: dict[str, Any]


@dataclass
class TenantContext:
    user: User
    organisation: Organisation
    membership: OrganisationMembership
    role_name: str
    permissions: list[str]


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> AuthenticatedPrincipal:
    """Validate Bearer JWT, check revocation list, and return the active User + token payload."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    jti = payload.get("jti")
    sub = payload.get("sub")

    if not jti or not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    revoked = db.execute(select(RevokedToken).where(RevokedToken.jti == jti)).scalar_one_or_none()
    if revoked is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = uuid.UUID(str(sub))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid subject identifier in token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.execute(select(User).where(User.id == user_uuid)).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user account no longer exists.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled.",
        )

    return AuthenticatedPrincipal(user=user, token_payload=payload)


def get_current_user(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> User:
    """Dependency returning the currently authenticated active User."""
    return principal.user


def resolve_organisation_membership(
    db: Session,
    user: User,
    organisation_id: uuid.UUID,
) -> TenantContext:
    """Validate that `user` is an ACTIVE member of `organisation_id`.

    Protects against cross-tenant IDOR: if the user does not belong to the organisation
    (or the organisation does not exist), raises 403 Forbidden so tenant existence
    is never leaked to unauthorised actors.
    """
    membership = (
        db.execute(
            select(OrganisationMembership).where(
                OrganisationMembership.user_id == user.id,
                OrganisationMembership.organisation_id == organisation_id,
                OrganisationMembership.status == MembershipStatus.ACTIVE,
            )
        )
        .scalars()
        .first()
    )

    if membership is None or membership.organisation is None or membership.role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: you are not an active member of this organisation.",
        )

    permissions = get_role_permissions(membership.role)
    return TenantContext(
        user=user,
        organisation=membership.organisation,
        membership=membership,
        role_name=membership.role.name,
        permissions=permissions,
    )


def get_path_tenant_context(
    organisation_id: uuid.UUID = Path(..., description="Target Organisation UUID"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenantContext:
    """Dependency resolving and validating organisation membership from `{organisation_id}` path parameter."""
    return resolve_organisation_membership(db=db, user=user, organisation_id=organisation_id)


def get_header_or_default_tenant_context(
    x_organisation_id: str | None = Header(default=None, alias="X-Organisation-ID"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TenantContext | None:
    """Resolve optional `X-Organisation-ID` header (validated against user memberships) or default to first active org."""
    if x_organisation_id:
        try:
            org_uuid = uuid.UUID(x_organisation_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid X-Organisation-ID header format.",
            ) from exc
        return resolve_organisation_membership(db=db, user=user, organisation_id=org_uuid)

    first_membership = (
        db.execute(
            select(OrganisationMembership)
            .where(
                OrganisationMembership.user_id == user.id,
                OrganisationMembership.status == MembershipStatus.ACTIVE,
            )
            .order_by(OrganisationMembership.joined_at.asc())
        )
        .scalars()
        .first()
    )
    if first_membership is None or first_membership.organisation is None or first_membership.role is None:
        return None

    return TenantContext(
        user=user,
        organisation=first_membership.organisation,
        membership=first_membership,
        role_name=first_membership.role.name,
        permissions=get_role_permissions(first_membership.role),
    )


def require_permission(required_permission: str) -> Callable[[TenantContext], TenantContext]:
    """Dependency factory enforcing a granular permission within the resolved `TenantContext`."""

    def _permission_dependency(
        context: TenantContext = Depends(get_path_tenant_context),
    ) -> TenantContext:
        if required_permission not in context.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Insufficient permissions: role '{context.role_name}' does not grant "
                    f"'{required_permission}' in this organisation."
                ),
            )
        return context

    return _permission_dependency
