"""Organisation and membership management routes with strict tenant isolation and RBAC."""
import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    TenantContext,
    get_current_user,
    get_path_tenant_context,
    require_permission,
)
from app.core.security import hash_password
from app.database import get_db
from app.models import (
    InvitationStatus,
    MembershipStatus,
    Organisation,
    OrganisationInvitation,
    OrganisationMembership,
    PermissionCode,
    RoleName,
    User,
    utcnow,
)
from app.schemas import (
    InvitationCreateRequest,
    InvitationCreateResponse,
    InvitationResponse,
    MemberAddRequest,
    MemberRoleUpdateRequest,
    MemberUserBrief,
    OrganisationCreateRequest,
    OrganisationDetailResponse,
    OrganisationMemberResponse,
    OrganisationUpdateRequest,
)
from app.services.invitation_service import create_organisation_invitation
from app.services.organisation_service import (
    count_active_admins,
    generate_unique_slug,
    get_role_by_name,
)
from app.services.rbac_service import get_role_permissions

router = APIRouter()


def _build_org_detail(
    db: Session,
    organisation: Organisation,
    role_name: str,
    permissions: list[str],
) -> OrganisationDetailResponse:
    member_count = int(
        db.execute(
            select(func.count(OrganisationMembership.id)).where(
                OrganisationMembership.organisation_id == organisation.id,
                OrganisationMembership.status == MembershipStatus.ACTIVE,
            )
        ).scalar_one()
        or 0
    )
    return OrganisationDetailResponse(
        id=organisation.id,
        name=organisation.name,
        slug=organisation.slug,
        description=organisation.description,
        created_by=organisation.created_by,
        created_at=organisation.created_at,
        updated_at=organisation.updated_at,
        current_user_role=role_name,
        current_user_permissions=permissions,
        member_count=member_count,
    )


def _build_member_response(membership: OrganisationMembership) -> OrganisationMemberResponse:
    assert membership.user is not None
    assert membership.role is not None
    return OrganisationMemberResponse(
        id=membership.id,
        organisation_id=membership.organisation_id,
        user=MemberUserBrief(
            id=membership.user.id,
            full_name=membership.user.full_name,
            email=membership.user.email,
            is_active=membership.user.is_active,
        ),
        role=membership.role.name,
        permissions=get_role_permissions(membership.role),
        status=membership.status,
        joined_at=membership.joined_at,
        created_at=membership.created_at,
    )


def _build_invitation_response(invite: OrganisationInvitation) -> InvitationResponse:
    invited_by_brief = None
    if invite.invited_by is not None:
        invited_by_brief = MemberUserBrief(
            id=invite.invited_by.id,
            full_name=invite.invited_by.full_name,
            email=invite.invited_by.email,
            is_active=invite.invited_by.is_active,
        )
    return InvitationResponse(
        id=invite.id,
        organisation_id=invite.organisation_id,
        email=invite.email,
        role=invite.role.name,
        status=invite.status,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
        accepted_at=invite.accepted_at,
        revoked_at=invite.revoked_at,
        invited_by=invited_by_brief,
    )


@router.post(
    "",
    response_model=OrganisationDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new organisation workspace and assign the creator as ADMIN",
)
def create_organisation(
    payload: OrganisationCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OrganisationDetailResponse:
    admin_role = get_role_by_name(db, RoleName.ADMIN)
    slug = generate_unique_slug(db, payload.name)

    try:
        org = Organisation(
            name=payload.name,
            slug=slug,
            description=payload.description,
            created_by=user.id,
        )
        db.add(org)
        db.flush()

        membership = OrganisationMembership(
            user_id=user.id,
            organisation_id=org.id,
            role_id=admin_role.id,
            status=MembershipStatus.ACTIVE,
        )
        db.add(membership)
        db.commit()
        db.refresh(org)
    except Exception:
        db.rollback()
        raise

    return _build_org_detail(
        db=db,
        organisation=org,
        role_name=admin_role.name,
        permissions=get_role_permissions(admin_role),
    )


@router.get(
    "",
    response_model=List[OrganisationDetailResponse],
    summary="List all organisations accessible to the authenticated user",
)
def list_user_organisations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[OrganisationDetailResponse]:
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

    results: list[OrganisationDetailResponse] = []
    for m in memberships:
        if m.organisation is None or m.role is None:
            continue
        results.append(
            _build_org_detail(
                db=db,
                organisation=m.organisation,
                role_name=m.role.name,
                permissions=get_role_permissions(m.role),
            )
        )
    return results


@router.get(
    "/{organisation_id}",
    response_model=OrganisationDetailResponse,
    summary="Get details for a specific organisation (requires active membership)",
)
def get_organisation(
    context: TenantContext = Depends(get_path_tenant_context),
    db: Session = Depends(get_db),
) -> OrganisationDetailResponse:
    return _build_org_detail(
        db=db,
        organisation=context.organisation,
        role_name=context.role_name,
        permissions=context.permissions,
    )


@router.patch(
    "/{organisation_id}",
    response_model=OrganisationDetailResponse,
    summary="Update organisation details (requires organisation:manage permission)",
)
def update_organisation(
    payload: OrganisationUpdateRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.ORGANISATION_MANAGE)),
    db: Session = Depends(get_db),
) -> OrganisationDetailResponse:
    org = context.organisation
    if payload.name is not None and payload.name != org.name:
        org.name = payload.name
    if "description" in payload.model_fields_set:
        org.description = payload.description

    db.add(org)
    db.commit()
    db.refresh(org)

    return _build_org_detail(
        db=db,
        organisation=org,
        role_name=context.role_name,
        permissions=context.permissions,
    )


@router.get(
    "/{organisation_id}/members",
    response_model=List[OrganisationMemberResponse],
    summary="List all members of an organisation (requires users:read permission)",
)
def list_organisation_members(
    context: TenantContext = Depends(require_permission(PermissionCode.USERS_READ)),
    db: Session = Depends(get_db),
) -> List[OrganisationMemberResponse]:
    memberships = (
        db.execute(
            select(OrganisationMembership)
            .where(OrganisationMembership.organisation_id == context.organisation.id)
            .order_by(OrganisationMembership.joined_at.asc())
        )
        .scalars()
        .all()
    )
    return [_build_member_response(m) for m in memberships if m.user is not None and m.role is not None]


@router.post(
    "/{organisation_id}/members",
    status_code=status.HTTP_400_BAD_REQUEST,
    summary="Direct member addition is disabled for security (use /invitations)",
)
def add_organisation_member(
    payload: MemberAddRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.USERS_MANAGE)),
    db: Session = Depends(get_db),
) -> None:
    """Direct member addition is strictly prohibited to guarantee explicit recipient consent and prevent enumeration.

    Invitations must be issued via POST /api/v1/organisations/{organisation_id}/invitations.
    """
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "Direct member addition without explicit invitation acceptance is disabled for security. "
            "Use POST /api/v1/organisations/{organisation_id}/invitations to invite team members."
        ),
    )


@router.post(
    "/{organisation_id}/invitations",
    response_model=InvitationCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a secure organisation invitation (requires users:manage permission)",
)
def create_invitation(
    payload: InvitationCreateRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.USERS_MANAGE)),
    db: Session = Depends(get_db),
) -> InvitationCreateResponse:
    """Create a cryptographically secure organisation invitation.

    Returns the raw high-entropy invitation token ONCE in the response for manual dispatch/testing.
    Stores ONLY the SHA-256 hash in PostgreSQL. Account existence is never disclosed.
    """
    target_role = get_role_by_name(db, payload.role)
    invitation, raw_token = create_organisation_invitation(
        db=db,
        organisation=context.organisation,
        inviter=context.membership.user,
        email=payload.email,
        target_role=target_role,
    )
    return InvitationCreateResponse(
        id=invitation.id,
        organisation_id=invitation.organisation_id,
        email=invitation.email,
        role=target_role.name,
        status=invitation.status,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
        invitation_token=raw_token,
        invitation_url=f"/accept-invitation?token={raw_token}",
        delivery_status="token_generated_for_manual_dispatch",
        message="Invitation created. In development/testing, copy the invitation link.",
    )


@router.get(
    "/{organisation_id}/invitations",
    response_model=List[InvitationResponse],
    summary="List all invitations for an organisation (requires users:read permission)",
)
def list_organisation_invitations(
    context: TenantContext = Depends(require_permission(PermissionCode.USERS_READ)),
    db: Session = Depends(get_db),
) -> List[InvitationResponse]:
    """List all invitations for the organisation. Never returns raw tokens or token hashes."""
    invitations = (
        db.execute(
            select(OrganisationInvitation)
            .where(OrganisationInvitation.organisation_id == context.organisation.id)
            .order_by(OrganisationInvitation.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [_build_invitation_response(inv) for inv in invitations]


@router.delete(
    "/{organisation_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a pending organisation invitation (requires users:manage permission)",
)
def revoke_invitation(
    invitation_id: uuid.UUID = Path(..., description="Target OrganisationInvitation UUID"),
    context: TenantContext = Depends(require_permission(PermissionCode.USERS_MANAGE)),
    db: Session = Depends(get_db),
) -> None:
    """Revoke a pending invitation, preventing it from being accepted."""
    invitation = (
        db.execute(
            select(OrganisationInvitation).where(
                OrganisationInvitation.id == invitation_id,
                OrganisationInvitation.organisation_id == context.organisation.id,
            )
        )
        .scalars()
        .first()
    )
    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation invitation not found.",
        )
    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot revoke invitation with status '{invitation.status}'.",
        )

    invitation.status = InvitationStatus.REVOKED
    invitation.revoked_at = utcnow()
    db.add(invitation)
    db.commit()


@router.patch(
    "/{organisation_id}/members/{membership_id}",
    response_model=OrganisationMemberResponse,
    summary="Change a member's role (requires users:manage; protects last active ADMIN)",
)
def update_member_role(
    payload: MemberRoleUpdateRequest,
    membership_id: uuid.UUID = Path(..., description="Target OrganisationMembership UUID"),
    context: TenantContext = Depends(require_permission(PermissionCode.USERS_MANAGE)),
    db: Session = Depends(get_db),
) -> OrganisationMemberResponse:
    membership = (
        db.execute(
            select(OrganisationMembership).where(
                OrganisationMembership.id == membership_id,
                OrganisationMembership.organisation_id == context.organisation.id,
            )
        )
        .scalars()
        .first()
    )
    if membership is None or membership.role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation membership not found.",
        )

    new_role = get_role_by_name(db, payload.role)
    admin_role = get_role_by_name(db, RoleName.ADMIN)

    if membership.role.name == RoleName.ADMIN and new_role.name != RoleName.ADMIN:
        active_admins = count_active_admins(
            db=db,
            organisation_id=context.organisation.id,
            admin_role_id=admin_role.id,
        )
        if active_admins <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot demote the last active ADMIN of the organisation.",
            )

    membership.role_id = new_role.id
    membership.role = new_role
    db.add(membership)
    db.commit()
    db.refresh(membership)

    return _build_member_response(membership)


@router.delete(
    "/{organisation_id}/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member from the organisation (requires users:manage; protects last active ADMIN)",
)
def remove_organisation_member(
    membership_id: uuid.UUID = Path(..., description="Target OrganisationMembership UUID"),
    context: TenantContext = Depends(require_permission(PermissionCode.USERS_MANAGE)),
    db: Session = Depends(get_db),
) -> None:
    membership = (
        db.execute(
            select(OrganisationMembership).where(
                OrganisationMembership.id == membership_id,
                OrganisationMembership.organisation_id == context.organisation.id,
            )
        )
        .scalars()
        .first()
    )
    if membership is None or membership.role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation membership not found.",
        )

    admin_role = get_role_by_name(db, RoleName.ADMIN)
    if membership.role.name == RoleName.ADMIN:
        active_admins = count_active_admins(
            db=db,
            organisation_id=context.organisation.id,
            admin_role_id=admin_role.id,
        )
        if active_admins <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last active ADMIN of the organisation.",
            )

    db.delete(membership)
    db.commit()
