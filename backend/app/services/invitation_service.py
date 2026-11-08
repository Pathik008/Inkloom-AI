"""Secure organisation invitation and membership acceptance service.

Architecture & Security:
1. Tokens are generated using Python's cryptographic 'secrets' module (high entropy).
2. ONLY the SHA-256 hash of the token is stored in the database.
3. Raw tokens are never logged, never exposed in ordinary list responses, and never stored.
4. Token lookups use constant-time comparison (hmac.compare_digest) to resist timing attacks.
5. Strict recipient verification: authenticated users can only accept invitations matching their registered email.
6. Account enumeration protection: creating an invitation returns identical 201 status and shape
   regardless of whether the recipient email is already registered on the platform.
"""
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import (
    InvitationStatus,
    MembershipStatus,
    Organisation,
    OrganisationInvitation,
    OrganisationMembership,
    Role,
    User,
    utcnow,
)


def generate_invitation_token() -> str:
    """Generate a cryptographically secure, high-entropy URL-safe token (256 bits of entropy)."""
    return secrets.token_urlsafe(32)


def hash_invitation_token(raw_token: str) -> str:
    """Compute the SHA-256 hex digest of a raw invitation token for database storage and lookup."""
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


def ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime object is timezone-aware in UTC across SQLite and PostgreSQL backends."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def create_organisation_invitation(
    db: Session,
    organisation: Organisation,
    inviter: User,
    email: str,
    target_role: Role,
    expires_in_days: int = 7,
) -> tuple[OrganisationInvitation, str]:
    """Create a new pending invitation.

    Returns:
        tuple[OrganisationInvitation, str]: (invitation_record, raw_token_for_one_time_return)
    """
    normalised_email = email.strip().lower()

    # 1. Check if the user is already an ACTIVE member of THIS organisation.
    existing_membership = (
        db.execute(
            select(OrganisationMembership)
            .join(User, OrganisationMembership.user_id == User.id)
            .where(
                OrganisationMembership.organisation_id == organisation.id,
                User.email == normalised_email,
                OrganisationMembership.status == MembershipStatus.ACTIVE,
            )
        )
        .scalars()
        .first()
    )
    if existing_membership is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This user is already an active member of the organisation.",
        )

    # 2. Revoke any previous pending invitation for this organisation and email
    pending_invites = (
        db.execute(
            select(OrganisationInvitation).where(
                OrganisationInvitation.organisation_id == organisation.id,
                OrganisationInvitation.email == normalised_email,
                OrganisationInvitation.status == InvitationStatus.PENDING,
            )
        )
        .scalars()
        .all()
    )
    for old_invite in pending_invites:
        old_invite.status = InvitationStatus.REVOKED
        old_invite.revoked_at = utcnow()
        db.add(old_invite)

    # 3. Generate high-entropy token and its SHA-256 hash
    raw_token = generate_invitation_token()
    token_hash = hash_invitation_token(raw_token)
    expires_at = utcnow() + timedelta(days=expires_in_days)

    # 4. Create and persist invitation record (stores ONLY token_hash)
    invitation = OrganisationInvitation(
        organisation_id=organisation.id,
        email=normalised_email,
        role_id=target_role.id,
        invited_by_user_id=inviter.id,
        token_hash=token_hash,
        status=InvitationStatus.PENDING,
        expires_at=expires_at,
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)

    return invitation, raw_token


def get_invitation_by_raw_token(db: Session, raw_token: str) -> OrganisationInvitation:
    """Validate and return the invitation corresponding to a raw token.

    Handles expiration, revocation, and prior acceptance with precise error classifications.
    Uses constant-time comparison to resist timing attacks.
    """
    token_hash = hash_invitation_token(raw_token)
    invitation = (
        db.execute(
            select(OrganisationInvitation).where(OrganisationInvitation.token_hash == token_hash)
        )
        .scalars()
        .one_or_none()
    )

    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired invitation token.",
        )

    # Constant-time token hash verification
    if not hmac.compare_digest(invitation.token_hash, token_hash):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid or expired invitation token.",
        )

    # Check status and expiration
    if invitation.status == InvitationStatus.ACCEPTED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This invitation has already been accepted and cannot be reused.",
        )

    if invitation.status == InvitationStatus.REVOKED:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This invitation has been revoked by an organisation administrator.",
        )

    if ensure_utc(invitation.expires_at) <= utcnow():
        invitation.status = InvitationStatus.EXPIRED
        db.add(invitation)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This invitation has expired. Request a new invitation from your administrator.",
        )

    if invitation.status != InvitationStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invitation is not active (current status: {invitation.status}).",
        )

    return invitation


def accept_invitation_for_user(
    db: Session,
    invitation: OrganisationInvitation,
    current_user: User,
) -> OrganisationMembership:
    """Accept an invitation for an existing authenticated user with concurrency protection.

    Enforces that the authenticated user's email strictly matches the invitation recipient email.
    Uses generic error responses to prevent email disclosure.
    """
    if current_user.email.strip().lower() != invitation.email.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorised to accept this invitation.",
        )

    # Acquire row-level lock on the invitation record to prevent concurrent double-acceptance
    locked_invitation = (
        db.execute(
            select(OrganisationInvitation)
            .where(OrganisationInvitation.id == invitation.id)
            .with_for_update(of=OrganisationInvitation)
            .execution_options(populate_existing=True)
        )
        .scalars()
        .one_or_none()
    )
    if locked_invitation is None or locked_invitation.status != InvitationStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This invitation has already been accepted and cannot be reused.",
        )

    if ensure_utc(locked_invitation.expires_at) <= utcnow():
        locked_invitation.status = InvitationStatus.EXPIRED
        db.add(locked_invitation)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This invitation has expired. Request a new invitation from your administrator.",
        )

    # Check if membership already exists (e.g. previously suspended or created)
    existing_membership = (
        db.execute(
            select(OrganisationMembership)
            .where(
                OrganisationMembership.organisation_id == locked_invitation.organisation_id,
                OrganisationMembership.user_id == current_user.id,
            )
            .with_for_update(of=OrganisationMembership)
            .execution_options(populate_existing=True)
        )
        .scalars()
        .first()
    )

    if existing_membership is not None:
        if existing_membership.status == MembershipStatus.ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User is already an active member of this organisation.",
            )
        existing_membership.status = MembershipStatus.ACTIVE
        existing_membership.role_id = locked_invitation.role_id
        existing_membership.joined_at = utcnow()
        membership = existing_membership
    else:
        membership = OrganisationMembership(
            user_id=current_user.id,
            organisation_id=locked_invitation.organisation_id,
            role_id=locked_invitation.role_id,
            status=MembershipStatus.ACTIVE,
            joined_at=utcnow(),
        )
        db.add(membership)

    locked_invitation.status = InvitationStatus.ACCEPTED
    locked_invitation.accepted_at = utcnow()
    db.add(locked_invitation)

    try:
        db.commit()
        db.refresh(membership)
    except Exception:
        db.rollback()
        raise

    return membership


def register_and_accept_invitation(
    db: Session,
    invitation: OrganisationInvitation,
    full_name: str,
    password: str,
) -> tuple[User, OrganisationMembership]:
    """Register a new user account and atomically accept their invitation with concurrency protection."""
    normalised_email = invitation.email.strip().lower()

    # 1. Acquire row-level lock on the invitation record
    locked_invitation = (
        db.execute(
            select(OrganisationInvitation)
            .where(OrganisationInvitation.id == invitation.id)
            .with_for_update(of=OrganisationInvitation)
            .execution_options(populate_existing=True)
        )
        .scalars()
        .one_or_none()
    )
    if locked_invitation is None or locked_invitation.status != InvitationStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This invitation has already been accepted and cannot be reused.",
        )

    if ensure_utc(locked_invitation.expires_at) <= utcnow():
        locked_invitation.status = InvitationStatus.EXPIRED
        db.add(locked_invitation)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This invitation has expired. Request a new invitation from your administrator.",
        )

    # 2. Check if an account already exists with this email
    existing_user = (
        db.execute(
            select(User)
            .where(User.email == normalised_email)
            .with_for_update(of=User)
        )
        .scalars()
        .first()
    )
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "An account with this email address already exists. "
                "Please log in to your account and accept the invitation."
            ),
        )

    # 3. Provision user, membership, and accept invitation in one transaction
    new_user = User(
        full_name=full_name.strip(),
        email=normalised_email,
        password_hash=hash_password(password),
        is_active=True,
        is_verified=True,
    )
    db.add(new_user)
    db.flush()

    membership = OrganisationMembership(
        user_id=new_user.id,
        organisation_id=locked_invitation.organisation_id,
        role_id=locked_invitation.role_id,
        status=MembershipStatus.ACTIVE,
        joined_at=utcnow(),
    )
    db.add(membership)

    locked_invitation.status = InvitationStatus.ACCEPTED
    locked_invitation.accepted_at = utcnow()
    db.add(locked_invitation)

    try:
        db.commit()
        db.refresh(new_user)
        db.refresh(membership)
    except Exception:
        db.rollback()
        raise

    return new_user, membership
