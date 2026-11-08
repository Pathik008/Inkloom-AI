"""Authentication API routes: register, login, logout, and current user (/me)."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    AuthenticatedPrincipal,
    TenantContext,
    get_current_principal,
    get_current_user,
    get_header_or_default_tenant_context,
)
from app.core.security import (
    create_access_token,
    enforce_auth_rate_limit,
    hash_password,
    verify_password,
)
from app.database import get_db
from app.models import (
    MembershipStatus,
    Organisation,
    OrganisationMembership,
    RevokedToken,
    RoleName,
    User,
)
from app.schemas import (
    AuthTokenResponse,
    CurrentUserResponse,
    LoginRequest,
    LogoutResponse,
    RegisterRequest,
)
from app.services.organisation_service import (
    build_current_user_response,
    generate_unique_slug,
    get_role_by_name,
)

router = APIRouter()


@router.post(
    "/register",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user and create their initial organisation as ADMIN",
    dependencies=[Depends(enforce_auth_rate_limit)],
)
def register_user(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
) -> AuthTokenResponse:
    """Create a User, an initial Organisation, and an ADMIN OrganisationMembership in one transaction."""
    existing_user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )

    admin_role = get_role_by_name(db, RoleName.ADMIN)
    slug = generate_unique_slug(db, payload.organisation_name)

    try:
        new_user = User(
            full_name=payload.full_name,
            email=payload.email,
            password_hash=hash_password(payload.password),
            is_active=True,
            is_verified=True,
        )
        db.add(new_user)
        db.flush()

        organisation = Organisation(
            name=payload.organisation_name,
            slug=slug,
            description=payload.organisation_description,
            created_by=new_user.id,
        )
        db.add(organisation)
        db.flush()

        membership = OrganisationMembership(
            user_id=new_user.id,
            organisation_id=organisation.id,
            role_id=admin_role.id,
            status=MembershipStatus.ACTIVE,
        )
        db.add(membership)
        db.commit()
        db.refresh(new_user)
    except Exception:
        db.rollback()
        raise

    token, _jti, expires_at = create_access_token(subject=new_user.id, email=new_user.email)
    user_response = build_current_user_response(db=db, user=new_user)
    return AuthTokenResponse(
        access_token=token,
        expires_at=expires_at,
        user=user_response,
    )


@router.post(
    "/login",
    response_model=AuthTokenResponse,
    summary="Authenticate with email and password and receive a JWT access token",
    dependencies=[Depends(enforce_auth_rate_limit)],
)
def login_user(
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> AuthTokenResponse:
    """Verify email and Argon2 password hash and issue a signed JWT access token."""
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled. Please contact your organisation administrator.",
        )

    token, _jti, expires_at = create_access_token(subject=user.id, email=user.email)
    user_response = build_current_user_response(db=db, user=user)
    return AuthTokenResponse(
        access_token=token,
        expires_at=expires_at,
        user=user_response,
    )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Revoke the current JWT access token immediately",
)
def logout_user(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> LogoutResponse:
    """Record the token's `jti` in `revoked_tokens` so it can no longer be used."""
    jti = str(principal.token_payload["jti"])
    exp_ts = int(principal.token_payload["exp"])
    expires_at = datetime.fromtimestamp(exp_ts, tz=timezone.utc)

    existing = db.execute(select(RevokedToken).where(RevokedToken.jti == jti)).scalar_one_or_none()
    if existing is None:
        db.add(
            RevokedToken(
                jti=jti,
                user_id=principal.user.id,
                expires_at=expires_at,
            )
        )
        db.commit()

    return LogoutResponse(
        message="Successfully logged out and revoked access token.",
        revoked_jti=jti,
    )


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    summary="Return the authenticated user's profile, organisations, roles, and permissions",
)
def get_me(
    user: User = Depends(get_current_user),
    active_context: TenantContext | None = Depends(get_header_or_default_tenant_context),
    db: Session = Depends(get_db),
) -> CurrentUserResponse:
    """Return current user details and organisation memberships without exposing secrets."""
    return build_current_user_response(db=db, user=user, active_context=active_context)
