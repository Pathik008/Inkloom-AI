"""Public and recipient-facing invitation API endpoints.

Lifecycle Endpoints:
- GET  /api/v1/invitations/{token}                  -> Public invitation preview
- POST /api/v1/invitations/{token}/accept           -> Authenticated existing user acceptance
- POST /api/v1/invitations/{token}/register-and-accept -> New user registration & immediate acceptance
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.rate_limit import (
    enforce_invitation_accept_rate_limit,
    enforce_invitation_preview_rate_limit,
    enforce_invitation_register_rate_limit,
)
from app.core.security import create_access_token
from app.database import get_db
from app.models import User
from app.schemas import (
    AuthTokenResponse,
    InvitationAcceptanceResponse,
    InvitationDetailPublic,
    InvitationRegisterAndAcceptRequest,
)
from app.services.invitation_service import (
    accept_invitation_for_user,
    get_invitation_by_raw_token,
    register_and_accept_invitation,
)
from app.services.organisation_service import build_current_user_response

router = APIRouter()


@router.get(
    "/{token}",
    response_model=InvitationDetailPublic,
    summary="Preview an organisation invitation by secure token",
    dependencies=[Depends(enforce_invitation_preview_rate_limit)],
)
def get_invitation_preview(
    token: str,
    db: Session = Depends(get_db),
) -> InvitationDetailPublic:
    """Validate token and return public invitation details without exposing internal account data."""
    invitation = get_invitation_by_raw_token(db=db, raw_token=token)
    return InvitationDetailPublic(
        id=invitation.id,
        organisation_name=invitation.organisation.name,
        email=invitation.email,
        role=invitation.role.name,
        expires_at=invitation.expires_at,
        status=invitation.status,
    )


@router.post(
    "/{token}/accept",
    response_model=InvitationAcceptanceResponse,
    summary="Accept an organisation invitation as an existing authenticated user",
    dependencies=[Depends(enforce_invitation_accept_rate_limit)],
)
def accept_invitation_authenticated(
    token: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvitationAcceptanceResponse:
    """Accept the invitation.

    The authenticated user's email MUST match the invitation recipient email.
    Creates an ACTIVE OrganisationMembership and marks the invitation ACCEPTED.
    """
    invitation = get_invitation_by_raw_token(db=db, raw_token=token)
    membership = accept_invitation_for_user(db=db, invitation=invitation, current_user=current_user)

    return InvitationAcceptanceResponse(
        message=f"Successfully joined {invitation.organisation.name} as {invitation.role.name}.",
        organisation_id=invitation.organisation_id,
        organisation_name=invitation.organisation.name,
        role=invitation.role.name,
        joined_at=membership.joined_at,
    )


@router.post(
    "/{token}/register-and-accept",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account and accept an organisation invitation",
    dependencies=[Depends(enforce_invitation_register_rate_limit)],
)
def register_and_accept_invitation_endpoint(
    token: str,
    payload: InvitationRegisterAndAcceptRequest,
    db: Session = Depends(get_db),
) -> AuthTokenResponse:
    """Register a new account bound to the invitation email and accept membership in one transaction."""
    invitation = get_invitation_by_raw_token(db=db, raw_token=token)
    new_user, membership = register_and_accept_invitation(
        db=db,
        invitation=invitation,
        full_name=payload.full_name,
        password=payload.password,
    )

    access_token, _, expires_at = create_access_token(
        subject=new_user.id,
        email=new_user.email,
    )
    user_response = build_current_user_response(
        db=db,
        user=new_user,
    )

    return AuthTokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_at=expires_at,
        user=user_response,
    )
