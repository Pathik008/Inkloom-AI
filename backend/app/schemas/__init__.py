"""Pydantic v2 request and response schemas for Inkloom AI."""
import re
import uuid
from datetime import datetime
from typing import Any, List
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


# ==============================================================================
# Brand Hub & Brand Kit Schemas (Stage 3.2)
# ==============================================================================


class BrandIdentityCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_name: str | None = Field(default=None, min_length=1, max_length=150)
    tagline: str | None = Field(default=None, max_length=255)
    mission_statement: str | None = Field(default=None, max_length=5000)
    brand_voice_tone: str | None = Field(default=None, max_length=255)
    brand_voice_guidelines: str | None = Field(default=None, max_length=5000)
    preferred_vocabulary: list[str] = Field(default_factory=list)
    prohibited_vocabulary: list[str] = Field(default_factory=list)
    color_palette: list[dict[str, Any]] = Field(default_factory=list)
    typography_rules: dict[str, Any] = Field(default_factory=dict)
    primary_color_hex: str | None = Field(default=None, max_length=7)
    secondary_color_hex: str | None = Field(default=None, max_length=7)
    accent_color_hex: str | None = Field(default=None, max_length=7)
    neutral_light_hex: str | None = Field(default=None, max_length=7)
    neutral_dark_hex: str | None = Field(default=None, max_length=7)
    primary_font_family: str | None = Field(default=None, max_length=120)
    secondary_font_family: str | None = Field(default=None, max_length=120)

    @field_validator(
        "primary_color_hex",
        "secondary_color_hex",
        "accent_color_hex",
        "neutral_light_hex",
        "neutral_dark_hex",
    )
    @classmethod
    def validate_hex_color(cls, value: str | None) -> str | None:
        if value is not None and not re.match(r"^#(?:[0-9a-fA-F]{3}){1,2}$", value):
            raise ValueError(f"'{value}' is not a valid 3- or 6-digit hex color (e.g. #FFFFFF).")
        return value


class BrandIdentityUpdateRequest(BrandIdentityCreateRequest):
    pass


class BrandIdentityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    brand_kit_version_id: uuid.UUID
    organisation_id: uuid.UUID
    brand_name: str
    tagline: str | None
    mission_statement: str | None
    brand_voice_tone: str | None
    brand_voice_guidelines: str | None
    preferred_vocabulary_json: list[str]
    prohibited_vocabulary_json: list[str]
    color_palette_json: list[dict[str, Any]]
    typography_rules_json: dict[str, Any]
    primary_color_hex: str | None
    secondary_color_hex: str | None
    accent_color_hex: str | None
    neutral_light_hex: str | None
    neutral_dark_hex: str | None
    primary_font_family: str | None
    secondary_font_family: str | None
    updated_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class BrandKitCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=2, max_length=150, description="Display name for the Brand Kit")
    slug: str | None = Field(default=None, min_length=2, max_length=160, description="Optional URL-safe unique slug within the organisation")
    description: str | None = Field(default=None, max_length=2000, description="Overview and purpose of this Brand Kit")
    industry: str | None = Field(default=None, max_length=100, description="Industry sector (e.g., SaaS, FinTech)")
    identity: BrandIdentityCreateRequest | None = Field(default=None, description="Optional initial brand identity parameters")

    @field_validator("name")
    @classmethod
    def strip_and_validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Brand Kit name must contain at least 2 non-whitespace characters.")
        return cleaned

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", cleaned):
            raise ValueError("Slug must consist of lowercase alphanumeric words separated by single hyphens.")
        return cleaned


class BrandKitUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=150)
    slug: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    industry: str | None = Field(default=None, max_length=100)
    is_archived: bool | None = Field(default=None, description="Set to true to archive the entire Brand Kit container")

    @field_validator("name")
    @classmethod
    def strip_and_validate_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Brand Kit name must contain at least 2 non-whitespace characters.")
        return cleaned

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", cleaned):
            raise ValueError("Slug must consist of lowercase alphanumeric words separated by single hyphens.")
        return cleaned


class BrandKitVersionSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    brand_kit_id: uuid.UUID
    organisation_id: uuid.UUID
    version_number: int
    status: str
    changelog: str | None
    cloned_from_version_id: uuid.UUID | None
    created_by_user_id: uuid.UUID | None
    published_by_user_id: uuid.UUID | None
    published_at: datetime | None
    archived_by_user_id: uuid.UUID | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BrandKitVersionDetailResponse(BrandKitVersionSummaryResponse):
    identity: BrandIdentityResponse | None = None
    facts_count: int = 0
    rules_count: int = 0
    assets_count: int = 0
    documents_count: int = 0


class BrandKitSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    industry: str | None
    active_version_id: uuid.UUID | None
    is_archived: bool
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    active_version: BrandKitVersionSummaryResponse | None = None
    draft_version: BrandKitVersionSummaryResponse | None = None


class BrandKitDetailResponse(BrandKitSummaryResponse):
    versions: list[BrandKitVersionSummaryResponse] = Field(default_factory=list)


class BrandKitVersionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changelog: str | None = Field(default=None, max_length=1000, description="Summary of changes planned for this draft")
    source_version_id: uuid.UUID | None = Field(default=None, description="Optional version UUID to clone content from; defaults to current active published version")


class BrandKitVersionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changelog: str | None = Field(default=None, max_length=1000)
    identity: BrandIdentityUpdateRequest | None = None


class SetActiveVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: uuid.UUID = Field(..., description="UUID of the PUBLISHED BrandKitVersion to make active")


# ==============================================================================
# Compliance Rules, Content Submission & Analysis Schemas (Phase 4)
# ==============================================================================

_RULE_TYPES = (
    "PROHIBITED_TERM",
    "MANDATORY_DISCLAIMER",
    "RESTRICTED_CLAIM",
    "PRICE_INTEGRITY",
    "TONE_CONSTRAINT",
    "MANDATORY_TERMINOLOGY",
)
_SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")
_MATCH_MODES = ("EXACT", "CASE_INSENSITIVE", "WORD_BOUNDARY", "REGEX")


class ComplianceRuleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_type: str = Field(..., description="PROHIBITED_TERM, MANDATORY_DISCLAIMER, MANDATORY_TERMINOLOGY, ...")
    title: str = Field(..., min_length=2, max_length=200)
    description: str = Field(..., min_length=2, max_length=2000)
    target_pattern: str = Field(..., min_length=1, max_length=300)
    rule_code: str | None = Field(default=None, min_length=2, max_length=64)
    severity: str = "HIGH"
    match_mode: str = "CASE_INSENSITIVE"
    priority: int = Field(default=100, ge=1, le=1000)
    required_disclaimer_text: str | None = Field(default=None, max_length=4000)
    suggested_replacement: str | None = Field(default=None, max_length=2000)
    rule_config: dict[str, Any] = Field(default_factory=dict)
    source_reference: str = Field(default="Manual entry", min_length=1, max_length=500)
    is_active: bool = True

    @field_validator("rule_type")
    @classmethod
    def _rt(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in _RULE_TYPES:
            raise ValueError(f"rule_type must be one of: {', '.join(_RULE_TYPES)}")
        return v

    @field_validator("severity")
    @classmethod
    def _sev(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in _SEVERITIES:
            raise ValueError(f"severity must be one of: {', '.join(_SEVERITIES)}")
        return v

    @field_validator("match_mode")
    @classmethod
    def _mm(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in _MATCH_MODES:
            raise ValueError(f"match_mode must be one of: {', '.join(_MATCH_MODES)}")
        return v


class ComplianceRuleUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, min_length=2, max_length=2000)
    target_pattern: str | None = Field(default=None, min_length=1, max_length=300)
    severity: str | None = None
    match_mode: str | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)
    required_disclaimer_text: str | None = Field(default=None, max_length=4000)
    suggested_replacement: str | None = Field(default=None, max_length=2000)
    rule_config: dict[str, Any] | None = None
    source_reference: str | None = Field(default=None, min_length=1, max_length=500)
    is_active: bool | None = None

    @field_validator("severity")
    @classmethod
    def _sev(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().upper()
        if v not in _SEVERITIES:
            raise ValueError(f"severity must be one of: {', '.join(_SEVERITIES)}")
        return v

    @field_validator("match_mode")
    @classmethod
    def _mm(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().upper()
        if v not in _MATCH_MODES:
            raise ValueError(f"match_mode must be one of: {', '.join(_MATCH_MODES)}")
        return v


class ComplianceRuleReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str | None = Field(default=None, max_length=2000)


class ComplianceRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    brand_kit_version_id: uuid.UUID
    organisation_id: uuid.UUID
    rule_code: str
    rule_type: str
    priority: int
    severity: str
    title: str
    description: str
    target_pattern: str
    match_mode: str
    required_disclaimer_text: str | None = None
    suggested_replacement: str | None = None
    rule_config_json: dict[str, Any] = Field(default_factory=dict)
    source_reference: str
    approval_status: str
    reviewed_by_user_id: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ContentSubmissionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_kit_id: uuid.UUID
    title: str = Field(default="Untitled content", min_length=1, max_length=200)
    content_text: str = Field(..., min_length=1, max_length=50000)

    @field_validator("content_text")
    @classmethod
    def _nonblank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content_text must not be blank.")
        return v


class ContentRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_text: str = Field(..., min_length=1, max_length=50000)
    title: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("content_text")
    @classmethod
    def _nonblank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content_text must not be blank.")
        return v


class ApplyCorrectionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_ids: list[str] | None = Field(
        default=None, description="Subset of finding IDs to correct. Omit to apply all available corrections."
    )


class ComplianceAnalysisResponse(BaseModel):
    id: uuid.UUID
    submission_id: uuid.UUID
    engine_version: str
    score: int
    result: str
    rules_evaluated: int
    findings: list[dict[str, Any]]
    scoring: dict[str, Any]
    created_at: datetime


class ReviewActionResponse(BaseModel):
    id: uuid.UUID
    submission_id: uuid.UUID
    actor_user_id: uuid.UUID | None = None
    actor_name: str | None = None
    actor_email: str | None = None
    action: str
    comments: str | None = None
    created_at: datetime


class ReviewerUserResponse(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    role: str


class AssignReviewerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer_id: uuid.UUID


class ApprovalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str = Field(..., description="'APPROVE', 'REJECT', or 'REQUEST_CHANGES'")
    comments: str | None = Field(default=None, max_length=5000)

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if cleaned not in ("APPROVE", "REJECT", "REQUEST_CHANGES"):
            raise ValueError("Decision must be APPROVE, REJECT, or REQUEST_CHANGES.")
        return cleaned


class AddCommentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comments: str = Field(..., min_length=1, max_length=5000)


class SubmitForApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assigned_reviewer_id: uuid.UUID | None = None
    comments: str | None = Field(default=None, max_length=5000)


class ContentSubmissionResponse(BaseModel):
    id: uuid.UUID
    organisation_id: uuid.UUID
    brand_kit_id: uuid.UUID
    brand_kit_version_id: uuid.UUID
    parent_submission_id: uuid.UUID | None = None
    revision_number: int
    title: str
    content_text: str
    submitted_by_user_id: uuid.UUID | None = None
    submitted_by_name: str | None = None
    created_at: datetime
    status: str = "DRAFT"
    assigned_reviewer_id: uuid.UUID | None = None
    assigned_reviewer_name: str | None = None
    reviewed_by_user_id: uuid.UUID | None = None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None
    reviewer_comments: str | None = None
    analysis: ComplianceAnalysisResponse | None = None
    comparison: dict[str, Any] | None = None
    correction_report: dict[str, Any] | None = None
    review_history: list[ReviewActionResponse] = Field(default_factory=list)
    all_revisions: list[dict[str, Any]] = Field(default_factory=list)


class ContentSubmissionSummaryResponse(BaseModel):
    id: uuid.UUID
    brand_kit_id: uuid.UUID
    brand_kit_version_id: uuid.UUID
    parent_submission_id: uuid.UUID | None = None
    revision_number: int
    title: str
    score: int | None = None
    result: str | None = None
    status: str = "DRAFT"
    assigned_reviewer_id: uuid.UUID | None = None
    assigned_reviewer_name: str | None = None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
