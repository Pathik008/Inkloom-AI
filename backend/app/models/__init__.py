"""SQLAlchemy ORM models for Phase 2: Authentication, Organisations, and RBAC."""
import uuid
from datetime import datetime, timezone
from typing import List
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RoleName:
    ADMIN = "ADMIN"
    BRAND_MANAGER = "BRAND_MANAGER"
    CONTENT_CREATOR = "CONTENT_CREATOR"
    REVIEWER = "REVIEWER"

    ALL = (ADMIN, BRAND_MANAGER, CONTENT_CREATOR, REVIEWER)


class MembershipStatus:
    ACTIVE = "ACTIVE"
    INVITED = "INVITED"
    SUSPENDED = "SUSPENDED"


class InvitationStatus:
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"

    ALL = (PENDING, ACCEPTED, REVOKED, EXPIRED)


class PermissionCode:
    USERS_READ = "users:read"
    USERS_MANAGE = "users:manage"
    ORGANISATION_MANAGE = "organisation:manage"
    BRAND_READ = "brand:read"
    BRAND_MANAGE = "brand:manage"
    CONTENT_CREATE = "content:create"
    CONTENT_EDIT = "content:edit"
    CONTENT_REVIEW = "content:review"
    APPROVAL_DECIDE = "approval:decide"
    AUDIT_READ = "audit:read"

    ALL_DESCRIPTIONS = {
        USERS_READ: "View organisation members and roles",
        USERS_MANAGE: "Invite, update roles, and remove organisation members",
        ORGANISATION_MANAGE: "Update organisation settings and profile",
        BRAND_READ: "View Brand Kits, approved facts, and compliance rules",
        BRAND_MANAGE: "Create, update, and publish Brand Kits and rules",
        CONTENT_CREATE: "Upload and create marketing content drafts",
        CONTENT_EDIT: "Edit marketing content and apply suggested corrections",
        CONTENT_REVIEW: "Run and inspect compliance review findings and evidence",
        APPROVAL_DECIDE: "Approve, reject, or request revisions on submitted content",
        AUDIT_READ: "View organisation security and compliance audit logs",
    }


ROLE_PERMISSION_MATRIX: dict[str, tuple[str, ...]] = {
    RoleName.ADMIN: (
        PermissionCode.USERS_READ,
        PermissionCode.USERS_MANAGE,
        PermissionCode.ORGANISATION_MANAGE,
        PermissionCode.BRAND_READ,
        PermissionCode.BRAND_MANAGE,
        PermissionCode.CONTENT_CREATE,
        PermissionCode.CONTENT_EDIT,
        PermissionCode.CONTENT_REVIEW,
        PermissionCode.APPROVAL_DECIDE,
        PermissionCode.AUDIT_READ,
    ),
    RoleName.BRAND_MANAGER: (
        PermissionCode.USERS_READ,
        PermissionCode.BRAND_READ,
        PermissionCode.BRAND_MANAGE,
        PermissionCode.CONTENT_REVIEW,
    ),
    RoleName.CONTENT_CREATOR: (
        PermissionCode.USERS_READ,
        PermissionCode.BRAND_READ,
        PermissionCode.CONTENT_CREATE,
        PermissionCode.CONTENT_EDIT,
        PermissionCode.CONTENT_REVIEW,
    ),
    RoleName.REVIEWER: (
        PermissionCode.USERS_READ,
        PermissionCode.BRAND_READ,
        PermissionCode.CONTENT_REVIEW,
        PermissionCode.APPROVAL_DECIDE,
    ),
}

ROLE_DESCRIPTIONS: dict[str, str] = {
    RoleName.ADMIN: "Full organisation-level administrative access across users, Brand Kits, reviews, approvals, and audits.",
    RoleName.BRAND_MANAGER: "Manage Brand Kits, guidelines, approved facts, rules, and review compliance reports.",
    RoleName.CONTENT_CREATOR: "Upload marketing content, review findings, edit drafts, and submit revisions for approval.",
    RoleName.REVIEWER: "Inspect compliance findings and supporting evidence, and approve, reject, or request revisions.",
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    memberships: Mapped[List["OrganisationMembership"]] = relationship(
        "OrganisationMembership",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Organisation(Base):
    __tablename__ = "organisations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    memberships: Mapped[List["OrganisationMembership"]] = relationship(
        "OrganisationMembership",
        back_populates="organisation",
        cascade="all, delete-orphan",
    )
    invitations: Mapped[List["OrganisationInvitation"]] = relationship(
        "OrganisationInvitation",
        back_populates="organisation",
        cascade="all, delete-orphan",
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    role_permissions: Mapped[List["RolePermission"]] = relationship(
        "RolePermission",
        back_populates="role",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    role_permissions: Mapped[List["RolePermission"]] = relationship(
        "RolePermission",
        back_populates="permission",
        cascade="all, delete-orphan",
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    role: Mapped["Role"] = relationship("Role", back_populates="role_permissions")
    permission: Mapped["Permission"] = relationship("Permission", back_populates="role_permissions", lazy="joined")


class OrganisationMembership(Base):
    __tablename__ = "organisation_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "organisation_id", name="uq_user_organisation_membership"),
        Index("ix_org_membership_org_role", "organisation_id", "role_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default=MembershipStatus.ACTIVE, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="memberships", lazy="joined")
    organisation: Mapped["Organisation"] = relationship("Organisation", back_populates="memberships", lazy="joined")
    role: Mapped["Role"] = relationship("Role", lazy="joined")


class OrganisationInvitation(Base):
    __tablename__ = "organisation_invitations"
    __table_args__ = (
        Index("ix_org_invitations_org_email", "organisation_id", "email"),
        Index("ix_org_invitations_org_status", "organisation_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    invited_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default=InvitationStatus.PENDING, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organisation: Mapped["Organisation"] = relationship("Organisation", back_populates="invitations")
    role: Mapped["Role"] = relationship("Role", lazy="joined")
    invited_by: Mapped["User"] = relationship("User", foreign_keys=[invited_by_user_id], lazy="joined")


class RevokedToken(Base):
    """Stores revoked JWT IDs (jti) to enforce immediate server-side token invalidation on logout."""

    __tablename__ = "revoked_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    jti: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


from app.models.brand import (  # noqa: E402
    ALLOWLISTED_GUIDELINE_DOC_TELEMETRY_COLUMNS,
    ApprovedBrandFact,
    BrandAsset,
    BrandAssetType,
    BrandAuditLog,
    BrandAuditResourceType,
    BrandDocumentChunk,
    BrandGuidelineDocument,
    BrandHubImmutabilityError,
    BrandIdentity,
    BrandKit,
    BrandKitVersion,
    BrandKitVersionStatus,
    ComplianceRule,
    ComplianceRuleType,
    DocumentParsingStatus,
    FactCategory,
    FactRuleApprovalStatus,
    GuidelineDocumentCategory,
    LOCKED_GUIDELINE_DOC_COLUMNS,
    ProvenanceSourceType,
    RuleMatchMode,
    RuleSeverity,
)
from app.models.compliance import (  # noqa: E402
    ComplianceAnalysis,
    ComplianceResult,
    ContentReviewAction,
    ContentSubmission,
    ReviewActionType,
    SubmissionStatus,
)

__all__ = [
    "ComplianceAnalysis",
    "ComplianceResult",
    "ContentReviewAction",
    "ContentSubmission",
    "ReviewActionType",
    "SubmissionStatus",
    "Base",
    "User",
    "Organisation",
    "Role",
    "Permission",
    "RolePermission",
    "OrganisationMembership",
    "OrganisationInvitation",
    "RevokedToken",
    "RoleName",
    "MembershipStatus",
    "InvitationStatus",
    "PermissionCode",
    "ROLE_PERMISSION_MATRIX",
    "ROLE_DESCRIPTIONS",
    "BrandHubImmutabilityError",
    "ALLOWLISTED_GUIDELINE_DOC_TELEMETRY_COLUMNS",
    "LOCKED_GUIDELINE_DOC_COLUMNS",
    "BrandKitVersionStatus",
    "ProvenanceSourceType",
    "FactRuleApprovalStatus",
    "FactCategory",
    "ComplianceRuleType",
    "RuleSeverity",
    "RuleMatchMode",
    "BrandAssetType",
    "GuidelineDocumentCategory",
    "DocumentParsingStatus",
    "BrandAuditResourceType",
    "BrandKit",
    "BrandKitVersion",
    "BrandIdentity",
    "ApprovedBrandFact",
    "ComplianceRule",
    "BrandAsset",
    "BrandGuidelineDocument",
    "BrandDocumentChunk",
    "BrandAuditLog",
]
