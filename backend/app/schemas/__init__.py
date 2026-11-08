"""Pydantic v2 request and response schemas for Inkloom AI."""
import re
import uuid
from datetime import datetime
from typing import List
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models import RoleName


class HealthResponse(BaseModel):
    status: str = Field(..., description="Overall API service status ('healthy' or 'degraded')")
    service: str = Field(..., description="Application name")
    version: str = Field(..., description="Application semantic version")
    environment: str = Field(..., description="Runtime environment")
    database_status: str = Field(..., description="Real-time database connectivity check result")
    database_connected: bool = Field(..., description="True if database responded to SELECT 1")
    pgvector_target_dimension: int = Field(..., description="Configured vector dimension for BAAI/bge-large-en-v1.5")
    timestamp: datetime = Field(..., description="UTC timestamp of health check")


# ==============================================================================
# Authentication & User Schemas
# ==============================================================================


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(..., min_length=2, max_length=150, description="User's full name")
    email: EmailStr = Field(..., description="User email address (normalised to lowercase)")
    password: str = Field(..., min_length=8, max_length=128, description="Strong password (min 8 chars)")
    confirm_password: str = Field(..., min_length=8, max_length=128, description="Password confirmation")
    organisation_name: str = Field(
        ..., min_length=2, max_length=150, description="Initial organisation workspace name"
    )
    organisation_description: str | None = Field(
        default=None, max_length=1000, description="Optional description of the organisation"
    )

    @field_validator("full_name", "organisation_name")
    @classmethod
    def strip_and_validate_non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Must be at least 2 non-whitespace characters.")
        return cleaned

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            raise ValueError("Password must contain at least one letter and one number.")
        return value

    @model_validator(mode="after")
    def check_passwords_match(self) -> "RegisterRequest":
        if self.password != self.confirm_password:
            raise ValueError("Password and confirm_password do not match.")
        return self


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(..., description="Registered email address")
    password: str = Field(..., min_length=1, max_length=128, description="Account password")

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str) -> str:
        return value.strip().lower()


class OrganisationSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class UserMembershipContextResponse(BaseModel):
    membership_id: uuid.UUID
    organisation: OrganisationSummaryResponse
    role: str
    permissions: List[str]
    status: str
    joined_at: datetime


class CurrentUserResponse(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    is_active: bool
    is_verified: bool
    created_at: datetime
    memberships: List[UserMembershipContextResponse]
    active_organisation_id: uuid.UUID | None = None
    active_role: str | None = None
    active_permissions: List[str] = Field(default_factory=list)


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: CurrentUserResponse


class LogoutResponse(BaseModel):
    message: str
    revoked_jti: str


# ==============================================================================
# Organisation & Membership Schemas
# ==============================================================================


class OrganisationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Organisation name must contain at least 2 characters.")
        return cleaned


class OrganisationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def strip_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Organisation name must contain at least 2 characters.")
        return cleaned


class OrganisationDetailResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    current_user_role: str
    current_user_permissions: List[str]
    member_count: int


class MemberUserBrief(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    is_active: bool


class OrganisationMemberResponse(BaseModel):
    id: uuid.UUID
    organisation_id: uuid.UUID
    user: MemberUserBrief
    role: str
    permissions: List[str]
    status: str
    joined_at: datetime
    created_at: datetime


class MemberAddRequest(BaseModel):
    """Add an existing user or provision a new organisation member (requires users:manage)."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(..., description="Email of user to add to the organisation")
    role: str = Field(..., description="Assigned role: ADMIN, BRAND_MANAGER, CONTENT_CREATOR, or REVIEWER")
    full_name: str | None = Field(
        default=None,
        min_length=2,
        max_length=150,
        description="Required only if provisioning a new user account directly in development workflow",
    )
    initial_password: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        description="Optional initial password if creating a new user account",
    )

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        upper = value.strip().upper()
        if upper not in RoleName.ALL:
            raise ValueError(f"Role must be one of: {', '.join(RoleName.ALL)}")
        return upper


class MemberRoleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(..., description="New role: ADMIN, BRAND_MANAGER, CONTENT_CREATOR, or REVIEWER")

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        upper = value.strip().upper()
        if upper not in RoleName.ALL:
            raise ValueError(f"Role must be one of: {', '.join(RoleName.ALL)}")
        return upper


# ==============================================================================
# Organisation Invitation Schemas (H2 Secure Lifecycle)
# ==============================================================================


class InvitationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(..., description="Recipient email address to invite")
    role: str = Field(..., description="Role to grant: ADMIN, BRAND_MANAGER, CONTENT_CREATOR, or REVIEWER")

    @field_validator("email")
    @classmethod
    def normalise_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        upper = value.strip().upper()
        if upper not in RoleName.ALL:
            raise ValueError(f"Role must be one of: {', '.join(RoleName.ALL)}")
        return upper


class InvitationCreateResponse(BaseModel):
    id: uuid.UUID
    organisation_id: uuid.UUID
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime
    invitation_token: str
    invitation_url: str
    delivery_status: str
    message: str


class InvitationResponse(BaseModel):
    id: uuid.UUID
    organisation_id: uuid.UUID
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None
    invited_by: MemberUserBrief | None = None


class InvitationDetailPublic(BaseModel):
    id: uuid.UUID
    organisation_name: str
    email: str
    role: str
    expires_at: datetime
    status: str


class InvitationRegisterAndAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(..., min_length=2, max_length=150, description="User's full name")
    password: str = Field(..., min_length=8, max_length=128, description="Strong password (min 8 chars)")
    confirm_password: str = Field(..., min_length=8, max_length=128, description="Password confirmation")

    @field_validator("full_name")
    @classmethod
    def strip_full_name(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Must be at least 2 non-whitespace characters.")
        return cleaned

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, value: str) -> str:
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            raise ValueError("Password must contain at least one letter and one number.")
        return value

    @model_validator(mode="after")
    def check_passwords_match(self) -> "InvitationRegisterAndAcceptRequest":
        if self.password != self.confirm_password:
            raise ValueError("Password and confirm_password do not match.")
        return self


class InvitationAcceptanceResponse(BaseModel):
    message: str
    organisation_id: uuid.UUID
    organisation_name: str
    role: str
    joined_at: datetime
