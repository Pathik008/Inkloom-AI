"""SQLAlchemy ORM models for Phase 3: Brand Hub (Versioned Brand Kits & Knowledge Base)."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, List

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    bindparam,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
     inspect as sa_inspect,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


JSONBVariant = JSONB().with_variant(JSON(), "sqlite")
Vector1024Variant = Vector(1024).with_variant(JSON(), "sqlite")


class BrandKitVersionStatus:
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"

    ALL = (DRAFT, PUBLISHED, ARCHIVED)


class ProvenanceSourceType:
    MANUAL_ENTRY = "MANUAL_ENTRY"
    GUIDELINE_DOCUMENT = "GUIDELINE_DOCUMENT"
    EXTERNAL_REGULATION = "EXTERNAL_REGULATION"
    AI_EXTRACTED = "AI_EXTRACTED"

    ALL = (MANUAL_ENTRY, GUIDELINE_DOCUMENT, EXTERNAL_REGULATION, AI_EXTRACTED)


class FactRuleApprovalStatus:
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"

    ALL = (PENDING_REVIEW, APPROVED, REJECTED)


class FactCategory:
    PRICING = "PRICING"
    PRODUCT_SPEC = "PRODUCT_SPEC"
    PROMOTION = "PROMOTION"
    CLAIM_EVIDENCE = "CLAIM_EVIDENCE"
    AVAILABILITY = "AVAILABILITY"
    GENERAL = "GENERAL"

    ALL = (PRICING, PRODUCT_SPEC, PROMOTION, CLAIM_EVIDENCE, AVAILABILITY, GENERAL)


class ComplianceRuleType:
    PROHIBITED_TERM = "PROHIBITED_TERM"
    MANDATORY_DISCLAIMER = "MANDATORY_DISCLAIMER"
    RESTRICTED_CLAIM = "RESTRICTED_CLAIM"
    PRICE_INTEGRITY = "PRICE_INTEGRITY"
    TONE_CONSTRAINT = "TONE_CONSTRAINT"
    MANDATORY_TERMINOLOGY = "MANDATORY_TERMINOLOGY"

    ALL = (
        PROHIBITED_TERM,
        MANDATORY_DISCLAIMER,
        RESTRICTED_CLAIM,
        PRICE_INTEGRITY,
        TONE_CONSTRAINT,
        MANDATORY_TERMINOLOGY,
    )


class RuleSeverity:
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

    ALL = (CRITICAL, HIGH, MEDIUM, LOW, INFO)


class RuleMatchMode:
    EXACT = "EXACT"
    CASE_INSENSITIVE = "CASE_INSENSITIVE"
    WORD_BOUNDARY = "WORD_BOUNDARY"
    REGEX = "REGEX"

    ALL = (EXACT, CASE_INSENSITIVE, WORD_BOUNDARY, REGEX)


class BrandAssetType:
    PRIMARY_LOGO = "PRIMARY_LOGO"
    SECONDARY_LOGO = "SECONDARY_LOGO"
    ICON = "ICON"
    BRAND_IMAGE = "BRAND_IMAGE"
    TYPOGRAPHY_SPEC = "TYPOGRAPHY_SPEC"

    ALL = (PRIMARY_LOGO, SECONDARY_LOGO, ICON, BRAND_IMAGE, TYPOGRAPHY_SPEC)


class GuidelineDocumentCategory:
    STYLE_GUIDE = "STYLE_GUIDE"
    PRODUCT_CATALOG = "PRODUCT_CATALOG"
    LEGAL_POLICY = "LEGAL_POLICY"
    TONE_PLAYBOOK = "TONE_PLAYBOOK"
    BRAND_BOOK = "BRAND_BOOK"

    ALL = (STYLE_GUIDE, PRODUCT_CATALOG, LEGAL_POLICY, TONE_PLAYBOOK, BRAND_BOOK)


class DocumentParsingStatus:
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PARSED = "PARSED"
    COMPLETED = "COMPLETED"
    EMBEDDED = "EMBEDDED"
    FAILED = "FAILED"

    ALL = (PENDING, PROCESSING, PARSED, COMPLETED, EMBEDDED, FAILED)


class BrandAuditResourceType:
    BRAND_KIT = "BRAND_KIT"
    VERSION = "VERSION"
    IDENTITY = "IDENTITY"
    FACT = "FACT"
    RULE = "RULE"
    ASSET = "ASSET"
    DOCUMENT = "DOCUMENT"

    ALL = (BRAND_KIT, VERSION, IDENTITY, FACT, RULE, ASSET, DOCUMENT)


class BrandKit(Base):
    """Top-level organisation-scoped Brand Kit container."""

    __tablename__ = "brand_kits"
    __table_args__ = (
        UniqueConstraint("id", "organisation_id", name="uq_brand_kits_id_org"),
        UniqueConstraint("organisation_id", "slug", name="uq_brand_kits_org_slug"),
        Index("ix_brand_kits_org_archived", "organisation_id", "is_archived"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "brand_kit_versions.id",
            name="fk_brand_kits_active_version_id",
            ondelete="SET NULL",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    organisation: Mapped["Organisation"] = relationship("Organisation", foreign_keys=[organisation_id])
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_user_id])
    versions: Mapped[List["BrandKitVersion"]] = relationship(
        "BrandKitVersion",
        back_populates="brand_kit",
        foreign_keys="[BrandKitVersion.brand_kit_id, BrandKitVersion.organisation_id]",
        primaryjoin="and_(BrandKit.id == BrandKitVersion.brand_kit_id, BrandKit.organisation_id == BrandKitVersion.organisation_id)",
        cascade="all, delete-orphan",
        order_by="BrandKitVersion.version_number.asc()",
    )
    active_version: Mapped["BrandKitVersion | None"] = relationship(
        "BrandKitVersion",
        foreign_keys=[active_version_id],
        post_update=True,
    )


class BrandKitVersion(Base):
    """Sequential version record for a Brand Kit (DRAFT -> PUBLISHED -> ARCHIVED)."""

    __tablename__ = "brand_kit_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["brand_kit_id", "organisation_id"],
            ["brand_kits.id", "brand_kits.organisation_id"],
            name="fk_brand_kit_versions_kit_org",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "organisation_id", name="uq_brand_kit_versions_id_org"),
        UniqueConstraint("id", "brand_kit_id", "organisation_id", name="uq_brand_kit_versions_id_kit_org"),
        UniqueConstraint("brand_kit_id", "version_number", name="uq_brand_kit_version_number"),
        CheckConstraint("version_number >= 1", name="ck_brand_kit_versions_version_number_pos"),
        CheckConstraint(
            "status IN ('DRAFT', 'PUBLISHED', 'ARCHIVED')",
            name="ck_brand_kit_versions_status",
        ),
        Index(
            "uq_brand_kit_single_draft",
            "brand_kit_id",
            unique=True,
            postgresql_where=text("status = 'DRAFT'"),
            sqlite_where=text("status = 'DRAFT'"),
        ),
        Index(
            "uq_brand_kit_single_published",
            "brand_kit_id",
            unique=True,
            postgresql_where=text("status = 'PUBLISHED'"),
            sqlite_where=text("status = 'PUBLISHED'"),
        ),
        Index("ix_brand_kit_versions_org_kit_status", "organisation_id", "brand_kit_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_kit_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=BrandKitVersionStatus.DRAFT, nullable=False, index=True
    )
    changelog: Mapped[str | None] = mapped_column(Text, nullable=True)
    cloned_from_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("brand_kit_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    brand_kit: Mapped["BrandKit"] = relationship(
        "BrandKit",
        back_populates="versions",
        foreign_keys=[brand_kit_id, organisation_id],
        primaryjoin="and_(BrandKitVersion.brand_kit_id == BrandKit.id, BrandKitVersion.organisation_id == BrandKit.organisation_id)",
    )
    cloned_from_version: Mapped["BrandKitVersion | None"] = relationship(
        "BrandKitVersion",
        remote_side=[id],
        foreign_keys=[cloned_from_version_id],
    )
    identity: Mapped["BrandIdentity | None"] = relationship(
        "BrandIdentity",
        back_populates="version",
        uselist=False,
        primaryjoin="and_(BrandKitVersion.id == BrandIdentity.brand_kit_version_id, BrandKitVersion.organisation_id == BrandIdentity.organisation_id)",
        cascade="all, delete-orphan",
    )
    facts: Mapped[List["ApprovedBrandFact"]] = relationship(
        "ApprovedBrandFact",
        back_populates="version",
        primaryjoin="and_(BrandKitVersion.id == ApprovedBrandFact.brand_kit_version_id, BrandKitVersion.organisation_id == ApprovedBrandFact.organisation_id)",
        cascade="all, delete-orphan",
    )
    rules: Mapped[List["ComplianceRule"]] = relationship(
        "ComplianceRule",
        back_populates="version",
        primaryjoin="and_(BrandKitVersion.id == ComplianceRule.brand_kit_version_id, BrandKitVersion.organisation_id == ComplianceRule.organisation_id)",
        cascade="all, delete-orphan",
    )
    assets: Mapped[List["BrandAsset"]] = relationship(
        "BrandAsset",
        back_populates="version",
        primaryjoin="and_(BrandKitVersion.id == BrandAsset.brand_kit_version_id, BrandKitVersion.organisation_id == BrandAsset.organisation_id)",
        cascade="all, delete-orphan",
    )
    documents: Mapped[List["BrandGuidelineDocument"]] = relationship(
        "BrandGuidelineDocument",
        back_populates="version",
        primaryjoin="and_(BrandKitVersion.id == BrandGuidelineDocument.brand_kit_version_id, BrandKitVersion.organisation_id == BrandGuidelineDocument.organisation_id)",
        cascade="all, delete-orphan",
    )


class BrandIdentity(Base):
    """1-to-1 brand identity configuration bound to a BrandKitVersion."""

    __tablename__ = "brand_identities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["brand_kit_version_id", "organisation_id"],
            ["brand_kit_versions.id", "brand_kit_versions.organisation_id"],
            name="fk_brand_identities_version_org",
            ondelete="CASCADE",
        ),
        UniqueConstraint("brand_kit_version_id", name="uq_brand_identities_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_kit_version_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    brand_name: Mapped[str] = mapped_column(String(150), nullable=False)
    tagline: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mission_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_voice_tone: Mapped[str | None] = mapped_column(String(255), nullable=True)
    brand_voice_guidelines: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_vocabulary_json: Mapped[list[str]] = mapped_column(
        JSONBVariant, default=list, nullable=False
    )
    prohibited_vocabulary_json: Mapped[list[str]] = mapped_column(
        JSONBVariant, default=list, nullable=False
    )
    color_palette_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONBVariant, default=list, nullable=False
    )
    typography_rules_json: Mapped[dict[str, Any]] = mapped_column(
        JSONBVariant, default=dict, nullable=False
    )
    primary_color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    secondary_color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    accent_color_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    neutral_light_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    neutral_dark_hex: Mapped[str | None] = mapped_column(String(7), nullable=True)
    primary_font_family: Mapped[str | None] = mapped_column(String(120), nullable=True)
    secondary_font_family: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    version: Mapped["BrandKitVersion"] = relationship(
        "BrandKitVersion",
        back_populates="identity",
        foreign_keys=[brand_kit_version_id],
        primaryjoin="and_(BrandIdentity.brand_kit_version_id == BrandKitVersion.id, BrandIdentity.organisation_id == BrandKitVersion.organisation_id)",
    )


class ApprovedBrandFact(Base):
    """Structured ground-truth brand fact with provenance and approval lifecycle."""

    __tablename__ = "approved_brand_facts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["brand_kit_version_id", "organisation_id"],
            ["brand_kit_versions.id", "brand_kit_versions.organisation_id"],
            name="fk_approved_brand_facts_version_org",
            ondelete="CASCADE",
        ),
        UniqueConstraint("brand_kit_version_id", "fact_key", name="uq_approved_brand_facts_version_key"),
        CheckConstraint(
            "approval_status IN ('PENDING_REVIEW', 'APPROVED', 'REJECTED')",
            name="ck_approved_brand_facts_approval_status",
        ),
        CheckConstraint(
            "source_type IN ('MANUAL_ENTRY', 'GUIDELINE_DOCUMENT', 'EXTERNAL_REGULATION', 'AI_EXTRACTED')",
            name="ck_approved_brand_facts_source_type",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="ck_approved_brand_facts_effective_dates",
        ),
        Index(
            "ix_approved_brand_facts_org_ver_cat",
            "organisation_id",
            "brand_kit_version_id",
            "category",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_kit_version_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_name: Mapped[str] = mapped_column(String(150), nullable=False)
    fact_key: Mapped[str] = mapped_column(String(150), nullable=False)
    fact_value: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)
    numeric_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_type: Mapped[str] = mapped_column(
        String(32), default=ProvenanceSourceType.MANUAL_ENTRY, nullable=False
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("brand_guideline_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    evidence_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_status: Mapped[str] = mapped_column(
        String(32), default=FactRuleApprovalStatus.PENDING_REVIEW, nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    version: Mapped["BrandKitVersion"] = relationship(
        "BrandKitVersion",
        back_populates="facts",
        foreign_keys=[brand_kit_version_id],
        primaryjoin="and_(ApprovedBrandFact.brand_kit_version_id == BrandKitVersion.id, ApprovedBrandFact.organisation_id == BrandKitVersion.organisation_id)",
    )
    source_document: Mapped["BrandGuidelineDocument | None"] = relationship(
        "BrandGuidelineDocument",
        foreign_keys=[source_document_id],
    )


class ComplianceRule(Base):
    """Structured compliance rule with provenance, priority, and approval lifecycle."""

    __tablename__ = "compliance_rules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["brand_kit_version_id", "organisation_id"],
            ["brand_kit_versions.id", "brand_kit_versions.organisation_id"],
            name="fk_compliance_rules_version_org",
            ondelete="CASCADE",
        ),
        UniqueConstraint("brand_kit_version_id", "rule_code", name="uq_compliance_rules_version_code"),
        CheckConstraint("priority BETWEEN 1 AND 1000", name="ck_compliance_rules_priority_range"),
        CheckConstraint(
            "severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO')",
            name="ck_compliance_rules_severity",
        ),
        CheckConstraint(
            "approval_status IN ('PENDING_REVIEW', 'APPROVED', 'REJECTED')",
            name="ck_compliance_rules_approval_status",
        ),
        CheckConstraint(
            "source_type IN ('MANUAL_ENTRY', 'GUIDELINE_DOCUMENT', 'EXTERNAL_REGULATION', 'AI_EXTRACTED')",
            name="ck_compliance_rules_source_type",
        ),
        CheckConstraint(
            "match_mode IN ('EXACT', 'CASE_INSENSITIVE', 'WORD_BOUNDARY', 'REGEX')",
            name="ck_compliance_rules_match_mode",
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="ck_compliance_rules_effective_dates",
        ),
        Index(
            "ix_compliance_rules_org_ver_type",
            "organisation_id",
            "brand_kit_version_id",
            "rule_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_kit_version_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default=RuleSeverity.HIGH, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    target_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    match_mode: Mapped[str] = mapped_column(
        String(32), default=RuleMatchMode.CASE_INSENSITIVE, nullable=False
    )
    required_disclaimer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_replacement: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_config_json: Mapped[dict[str, Any]] = mapped_column(
        JSONBVariant, default=dict, nullable=False
    )
    source_type: Mapped[str] = mapped_column(
        String(32), default=ProvenanceSourceType.MANUAL_ENTRY, nullable=False
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("brand_guideline_documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    evidence_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_status: Mapped[str] = mapped_column(
        String(32), default=FactRuleApprovalStatus.PENDING_REVIEW, nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    version: Mapped["BrandKitVersion"] = relationship(
        "BrandKitVersion",
        back_populates="rules",
        foreign_keys=[brand_kit_version_id],
        primaryjoin="and_(ComplianceRule.brand_kit_version_id == BrandKitVersion.id, ComplianceRule.organisation_id == BrandKitVersion.organisation_id)",
    )
    source_document: Mapped["BrandGuidelineDocument | None"] = relationship(
        "BrandGuidelineDocument",
        foreign_keys=[source_document_id],
    )


class BrandAsset(Base):
    """Versioned media asset (logo, icon, brand image, typography spec) with SHA-256 verification."""

    __tablename__ = "brand_assets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["brand_kit_version_id", "organisation_id"],
            ["brand_kit_versions.id", "brand_kit_versions.organisation_id"],
            name="fk_brand_assets_version_org",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "file_size_bytes > 0 AND file_size_bytes <= 10485760",
            name="ck_brand_assets_file_size",
        ),
        Index(
            "ix_brand_assets_org_ver_type",
            "organisation_id",
            "brand_kit_version_id",
            "asset_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_kit_version_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(32), default="LOCAL", nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    asset_metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONBVariant, default=dict, nullable=False
    )
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    version: Mapped["BrandKitVersion"] = relationship(
        "BrandKitVersion",
        back_populates="assets",
        foreign_keys=[brand_kit_version_id],
        primaryjoin="and_(BrandAsset.brand_kit_version_id == BrandKitVersion.id, BrandAsset.organisation_id == BrandKitVersion.organisation_id)",
    )


class BrandGuidelineDocument(Base):
    """Versioned brand guideline document with SHA-256 verification and processing telemetry."""

    __tablename__ = "brand_guideline_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["brand_kit_version_id", "organisation_id"],
            ["brand_kit_versions.id", "brand_kit_versions.organisation_id"],
            name="fk_brand_guideline_docs_version_org",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "id",
            "brand_kit_version_id",
            "organisation_id",
            name="uq_brand_guideline_docs_id_ver_org",
        ),
        CheckConstraint(
            "file_size_bytes > 0 AND file_size_bytes <= 26214400",
            name="ck_brand_guideline_docs_file_size",
        ),
        CheckConstraint("parse_attempt_count >= 0", name="ck_brand_guideline_docs_attempt_count"),
        CheckConstraint(
            "parsing_status IN ('PENDING', 'PROCESSING', 'PARSED', 'COMPLETED', 'EMBEDDED', 'FAILED')",
            name="ck_brand_guideline_docs_parsing_status",
        ),
        Index(
            "ix_brand_guideline_docs_org_ver_status",
            "organisation_id",
            "brand_kit_version_id",
            "parsing_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    brand_kit_version_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    document_category: Mapped[str] = mapped_column(
        String(64), default=GuidelineDocumentCategory.STYLE_GUIDE, nullable=False
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(32), default="LOCAL", nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parsing_status: Mapped[str] = mapped_column(
        String(32), default=DocumentParsingStatus.PENDING, nullable=False, index=True
    )
    parse_attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    embedding_model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    version: Mapped["BrandKitVersion"] = relationship(
        "BrandKitVersion",
        back_populates="documents",
        foreign_keys=[brand_kit_version_id],
        primaryjoin="and_(BrandGuidelineDocument.brand_kit_version_id == BrandKitVersion.id, BrandGuidelineDocument.organisation_id == BrandKitVersion.organisation_id)",
    )
    chunks: Mapped[List["BrandDocumentChunk"]] = relationship(
        "BrandDocumentChunk",
        back_populates="document",
        primaryjoin="and_(BrandGuidelineDocument.id == BrandDocumentChunk.document_id, BrandGuidelineDocument.brand_kit_version_id == BrandDocumentChunk.brand_kit_version_id, BrandGuidelineDocument.organisation_id == BrandDocumentChunk.organisation_id)",
        cascade="all, delete-orphan",
        order_by="BrandDocumentChunk.chunk_index.asc()",
    )


class BrandDocumentChunk(Base):
    """RAG document chunk with 1024-dimensional pgvector embedding bound to a BrandKitVersion."""

    __tablename__ = "brand_document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "brand_kit_version_id", "organisation_id"],
            [
                "brand_guideline_documents.id",
                "brand_guideline_documents.brand_kit_version_id",
                "brand_guideline_documents.organisation_id",
            ],
            name="fk_brand_doc_chunks_doc_ver_org",
            ondelete="CASCADE",
        ),
        UniqueConstraint("document_id", "chunk_index", name="uq_brand_doc_chunks_doc_index"),
        CheckConstraint("chunk_index >= 0", name="ck_brand_doc_chunks_index_nonneg"),
        CheckConstraint(
            "char_end >= char_start AND char_start >= 0",
            name="ck_brand_doc_chunks_char_bounds",
        ),
        CheckConstraint("token_count > 0", name="ck_brand_doc_chunks_token_count_pos"),
        CheckConstraint("embedding_dimension = 1024", name="ck_brand_doc_chunks_embedding_dim"),
        Index(
            "ix_brand_doc_chunks_org_ver_doc",
            "organisation_id",
            "brand_kit_version_id",
            "document_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    brand_kit_version_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_heading: Mapped[str | None] = mapped_column(String(255), nullable=True)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[Any | None] = mapped_column(Vector1024Variant, nullable=True)
    embedding_model: Mapped[str] = mapped_column(
        String(120), default="BAAI/bge-large-en-v1.5", nullable=False
    )
    embedding_model_version: Mapped[str] = mapped_column(String(64), default="1.5", nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, default=1024, nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSONBVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    document: Mapped["BrandGuidelineDocument"] = relationship(
        "BrandGuidelineDocument",
        back_populates="chunks",
        foreign_keys=[document_id],
        primaryjoin="and_(BrandDocumentChunk.document_id == BrandGuidelineDocument.id, BrandDocumentChunk.brand_kit_version_id == BrandGuidelineDocument.brand_kit_version_id, BrandDocumentChunk.organisation_id == BrandGuidelineDocument.organisation_id)",
    )


class BrandAuditLog(Base):
    """Append-only tenant-scoped audit trail for Brand Hub operations."""

    __tablename__ = "brand_audit_logs"
    __table_args__ = (
        Index(
            "ix_brand_audit_logs_org_kit_created",
            "organisation_id",
            "brand_kit_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    brand_kit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("brand_kits.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    brand_kit_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("brand_kit_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSONBVariant, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


class BrandHubImmutabilityError(ValueError):
    """Raised by the SQLAlchemy ORM before_flush listener when Brand Hub immutability is violated."""


LOCKED_BRAND_KIT_VERSION_STRUCTURAL_COLUMNS: frozenset[str] = frozenset(
    {
        "id",
        "brand_kit_id",
        "organisation_id",
        "version_number",
    }
)

LOCKED_BRAND_KIT_VERSION_SNAPSHOT_COLUMNS_ON_ARCHIVE: frozenset[str] = frozenset(
    {
        "changelog",
        "cloned_from_version_id",
        "created_by_user_id",
        "published_by_user_id",
        "published_at",
        "created_at",
    }
)

ALLOWLISTED_GUIDELINE_DOC_TELEMETRY_COLUMNS: frozenset[str] = frozenset(
    {
        "parsing_status",
        "parse_attempt_count",
        "last_error_code",
        "last_error_message",
        "page_count",
        "raw_text_content",
        "embedding_model",
        "embedding_model_version",
        "parsed_at",
        "embedded_at",
    }
)

LOCKED_GUIDELINE_DOC_COLUMNS: frozenset[str] = frozenset(
    {
        "id",
        "brand_kit_version_id",
        "organisation_id",
        "title",
        "document_category",
        "original_filename",
        "stored_filename",
        "storage_backend",
        "storage_path",
        "mime_type",
        "file_size_bytes",
        "file_sha256",
        "uploaded_by_user_id",
        "created_at",
    }
)

_PROTECTED_VERSION_STATUSES: frozenset[str] = frozenset(
    {
        BrandKitVersionStatus.PUBLISHED,
        BrandKitVersionStatus.ARCHIVED,
    }
)

_STRICT_VERSION_CHILD_MODELS = (
    BrandIdentity,
    ApprovedBrandFact,
    ComplianceRule,
    BrandAsset,
    BrandDocumentChunk,
)

_ALL_VERSION_CHILD_MODELS = _STRICT_VERSION_CHILD_MODELS + (BrandGuidelineDocument,)


def _raise_immutability_error(message: str) -> None:
    raise IntegrityError(
        statement="ORM before_flush immutability check",
        params=None,
        orig=BrandHubImmutabilityError(message),
    )


def _normalize_uuid(val: Any) -> uuid.UUID | None:
    if val is None:
        return None
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError):
        return None


def _normalize_enum_or_scalar(val: Any) -> Any:
    if isinstance(val, Enum):
        return val.value
    return val


def _normalize_comparable_value(val: Any) -> Any:
    val = _normalize_enum_or_scalar(val)
    if isinstance(val, uuid.UUID):
        return val
    if isinstance(val, datetime):
        if val.tzinfo is not None:
            return val.astimezone(timezone.utc).replace(tzinfo=None)
        return val
    return val


def _values_are_equal(old_val: Any, new_val: Any) -> bool:
    if isinstance(old_val, uuid.UUID) or isinstance(new_val, uuid.UUID):
        norm_old_uuid = _normalize_uuid(old_val)
        norm_new_uuid = _normalize_uuid(new_val)
        if norm_old_uuid is not None or norm_new_uuid is not None:
            return norm_old_uuid == norm_new_uuid
    return _normalize_comparable_value(old_val) == _normalize_comparable_value(new_val)


def _get_object_id_no_load(obj: Any) -> uuid.UUID | None:
    """Return the UUID primary key of an ORM instance without triggering any attribute or relationship load."""
    state = sa_inspect(obj)
    if state.has_identity and state.identity:
        return _normalize_uuid(state.identity[0])
    return _normalize_uuid(state.dict.get("id"))


@event.listens_for(Session, "before_flush")
def _enforce_brand_hub_immutability_before_flush(
    session: Session,
    flush_context: Any,
    instances: Any,
) -> None:
    """Enforce Brand Hub version, child, and audit-log immutability at the SQLAlchemy ORM layer.

    Separation of Responsibilities:
    - This Session.before_flush listener is an ORM-level defence-in-depth safeguard that catches
      prohibited mutations early in Python (and enforces immutability in SQLite unit tests).
    - PostgreSQL triggers (migrations 0003 and 0005) remain the authoritative database enforcement
      layer for raw SQL, SQLAlchemy Core DML (update/delete/insert), and external database clients.
    - This listener intentionally does not reproduce PostgreSQL trigger side-effects (such as
      server-generated published_at/archived_at timestamps or clearing brand_kits.active_version_id)
      nor all database-level composite foreign-key/cross-tenant reference validations.
    """
    # Fast path if session has no Brand Hub models in new, dirty, or deleted
    has_relevant = False
    for collection in (session.new, session.dirty, session.deleted):
        for obj in collection:
            if isinstance(
                obj,
                (
                    BrandKitVersion,
                    BrandIdentity,
                    ApprovedBrandFact,
                    ComplianceRule,
                    BrandAsset,
                    BrandGuidelineDocument,
                    BrandDocumentChunk,
                    BrandAuditLog,
                ),
            ):
                has_relevant = True
                break
        if has_relevant:
            break

    if not has_relevant:
        return

    persisted_row_cache: dict[tuple[type[Any], uuid.UUID], dict[str, Any] | None] = {}

    def _get_persisted_row(state: Any) -> dict[str, Any] | None:
        """Fetch and cache the persisted database row for a persistent ORM state inside session.no_autoflush.

        Never queries the database for pending/new objects (state.has_identity is False)
        and never triggers relationship lazy loads.
        """
        if not state.has_identity or not state.identity:
            return None
        pk_id = _normalize_uuid(state.identity[0])
        if pk_id is None:
            return None
        model_cls = state.class_
        cache_key = (model_cls, pk_id)
        if cache_key in persisted_row_cache:
            return persisted_row_cache[cache_key]
        table = model_cls.__table__
        with session.no_autoflush:
            row_mapping = (
                session.execute(select(table).where(table.c.id == pk_id))
                .mappings()
                .first()
            )
        row_dict = dict(row_mapping) if row_mapping is not None else None
        persisted_row_cache[cache_key] = row_dict
        return row_dict

    def _get_old_and_new_value(state: Any, key: str) -> tuple[Any, Any]:
        """Return (old_persisted_value, current_new_value) for a mapped column attribute.

        When an object is persistent and attribute history does not contain the previous value
        (e.g., after session.commit(), session.expire(), session.expire_all(), or deferred loading),
        retrieves the original persisted value from the database by primary key inside
        session.no_autoflush without substituting the newly assigned value.
        """
        hist = state.attrs[key].history

        if key in state.dict:
            new_val = state.dict[key]
        elif hist.added:
            new_val = hist.added[0]
        elif state.has_identity:
            persisted = _get_persisted_row(state)
            new_val = persisted.get(key) if persisted is not None else None
        else:
            new_val = None

        if not state.has_identity:
            old_val = new_val
        elif hist.deleted:
            old_val = hist.deleted[0]
        elif not hist.has_changes() and key in state.dict:
            old_val = state.dict[key]
        else:
            persisted = _get_persisted_row(state)
            old_val = persisted.get(key) if persisted is not None else None

        return _normalize_enum_or_scalar(old_val), _normalize_enum_or_scalar(new_val)

    def _get_changed_mapped_columns(state: Any) -> set[str]:
        """Return mapped column attribute keys whose value changed relative to the persisted state."""
        changed: set[str] = set()
        for col_attr in state.mapper.column_attrs:
            key = col_attr.key
            hist = state.attrs[key].history
            if not hist.has_changes():
                continue
            old_val, new_val = _get_old_and_new_value(state, key)
            if _values_are_equal(old_val, new_val):
                continue
            changed.add(key)
        return changed

    # Track organisations and BrandKits/draft versions being deleted in this flush
    deleted_org_ids: set[uuid.UUID] = set()
    deleted_kit_ids: set[uuid.UUID] = set()
    deleted_version_ids: set[uuid.UUID] = set()
    for obj in session.deleted:
        tablename = getattr(obj, "__tablename__", None)
        if tablename == "organisations":
            oid = _get_object_id_no_load(obj)
            if oid is not None:
                deleted_org_ids.add(oid)
        elif isinstance(obj, BrandKit):
            kid = _get_object_id_no_load(obj)
            if kid is not None:
                deleted_kit_ids.add(kid)
        elif isinstance(obj, BrandKitVersion):
            vid = _get_object_id_no_load(obj)
            if vid is not None:
                deleted_version_ids.add(vid)

    org_exists_cache: dict[uuid.UUID, bool] = {}

    def _is_organisation_being_deleted(org_id_raw: Any) -> bool:
        org_id = _normalize_uuid(org_id_raw)
        if org_id is None:
            return False
        if org_id in deleted_org_ids:
            return True
        if org_id in org_exists_cache:
            return not org_exists_cache[org_id]
        with session.no_autoflush:
            exists_row = session.execute(
                text("SELECT 1 FROM organisations WHERE id = :oid").bindparams(
                    bindparam("oid", type_=Uuid(as_uuid=True))
                ),
                {"oid": org_id},
            ).first()
        exists = exists_row is not None
        org_exists_cache[org_id] = exists
        return not exists

    # Build a lookup of all BrandKitVersion instances currently tracked in the session
    session_versions: dict[uuid.UUID, BrandKitVersion] = {}
    for ver_obj in list(session.identity_map.values()) + list(session.new) + list(session.deleted):
        if isinstance(ver_obj, BrandKitVersion):
            vid = _get_object_id_no_load(ver_obj)
            if vid is not None:
                session_versions[vid] = ver_obj

    db_version_status_cache: dict[uuid.UUID, str | None] = {}

    def _resolve_version_status_by_id(version_id_raw: Any) -> str | None:
        vid = _normalize_uuid(version_id_raw)
        if vid is None:
            return None
        if vid in session_versions:
            ver_obj = session_versions[vid]
            ver_state = sa_inspect(ver_obj)
            old_st, new_st = _get_old_and_new_value(ver_state, "status")
            if old_st in _PROTECTED_VERSION_STATUSES:
                return old_st
            return new_st
        if vid in db_version_status_cache:
            return db_version_status_cache[vid]
        with session.no_autoflush:
            status_val = session.execute(
                select(BrandKitVersion.status).where(BrandKitVersion.id == vid)
            ).scalar_one_or_none()
        norm_status = _normalize_enum_or_scalar(status_val)
        db_version_status_cache[vid] = norm_status
        return norm_status

    def _resolve_child_version_id_and_status(child_obj: Any, use_old: bool = False) -> tuple[Any, str | None]:
        child_state = sa_inspect(child_obj)
        old_vid, new_vid = _get_old_and_new_value(child_state, "brand_kit_version_id")
        target_vid = old_vid if use_old else new_vid
        if target_vid is not None:
            return target_vid, _resolve_version_status_by_id(target_vid)

        # Fallback only to already-loaded in-memory relationships in state.dict (never triggers lazy load)
        loaded_ver = child_state.dict.get("version")
        if isinstance(loaded_ver, BrandKitVersion):
            ver_state = sa_inspect(loaded_ver)
            old_st, new_st = _get_old_and_new_value(ver_state, "status")
            eff_st = old_st if old_st in _PROTECTED_VERSION_STATUSES else new_st
            return _get_object_id_no_load(loaded_ver), eff_st

        if isinstance(child_obj, BrandDocumentChunk):
            loaded_doc = child_state.dict.get("document")
            if isinstance(loaded_doc, BrandGuidelineDocument):
                doc_state = sa_inspect(loaded_doc)
                _, doc_vid = _get_old_and_new_value(doc_state, "brand_kit_version_id")
                if doc_vid is not None:
                    return doc_vid, _resolve_version_status_by_id(doc_vid)
                doc_ver = doc_state.dict.get("version")
                if isinstance(doc_ver, BrandKitVersion):
                    ver_state = sa_inspect(doc_ver)
                    old_st, new_st = _get_old_and_new_value(ver_state, "status")
                    eff_st = old_st if old_st in _PROTECTED_VERSION_STATUSES else new_st
                    return _get_object_id_no_load(doc_ver), eff_st

        return None, None

    # ------------------------------------------------------------------
    # 1. Validate BrandKitVersion DELETE and UPDATE rules
    # ------------------------------------------------------------------
    for obj in session.deleted:
        if isinstance(obj, BrandKitVersion):
            state = sa_inspect(obj)
            obj_id = _get_object_id_no_load(obj)
            old_status, _ = _get_old_and_new_value(state, "status")
            old_org_id, _ = _get_old_and_new_value(state, "organisation_id")
            if old_status in _PROTECTED_VERSION_STATUSES and not _is_organisation_being_deleted(old_org_id):
                _raise_immutability_error(
                    f"[P0001] Cannot delete a {old_status} BrandKitVersion (id={obj_id}). "
                    "Published and archived versions are immutable."
                )

    for obj in session.dirty:
        if isinstance(obj, BrandKitVersion) and obj not in session.deleted:
            state = sa_inspect(obj)
            obj_id = _get_object_id_no_load(obj)
            changed_cols = _get_changed_mapped_columns(state)
            if not changed_cols:
                continue

            # Structural identity columns cannot change once persistent
            if changed_cols & LOCKED_BRAND_KIT_VERSION_STRUCTURAL_COLUMNS:
                _raise_immutability_error(
                    f"[P0001] Cannot modify structural identity columns "
                    f"(id, brand_kit_id, organisation_id, version_number) of BrandKitVersion (id={obj_id})."
                )

            old_status, new_status = _get_old_and_new_value(state, "status")

            if new_status not in BrandKitVersionStatus.ALL:
                _raise_immutability_error(
                    f"[P0003] Invalid status '{new_status}' for BrandKitVersion (id={obj_id}). "
                    f"Permitted statuses are: {', '.join(BrandKitVersionStatus.ALL)}."
                )

            if old_status == BrandKitVersionStatus.DRAFT:
                if new_status == BrandKitVersionStatus.ARCHIVED:
                    _raise_immutability_error(
                        f"[P0003] Invalid status transition from DRAFT to ARCHIVED for BrandKitVersion (id={obj_id}). "
                        "A draft must be published before archiving."
                    )
            elif old_status == BrandKitVersionStatus.ARCHIVED:
                _raise_immutability_error(
                    f"[P0003] BrandKitVersion (id={obj_id}) is ARCHIVED (terminal state) "
                    f"and cannot be modified or restored to {new_status}."
                )
            elif old_status == BrandKitVersionStatus.PUBLISHED:
                if new_status != BrandKitVersionStatus.ARCHIVED:
                    _raise_immutability_error(
                        f"[P0001] Cannot modify a PUBLISHED BrandKitVersion (id={obj_id}). "
                        "Only transition to ARCHIVED is permitted."
                    )
                if changed_cols & LOCKED_BRAND_KIT_VERSION_SNAPSHOT_COLUMNS_ON_ARCHIVE:
                    _raise_immutability_error(
                        f"[P0001] Cannot modify immutable snapshot columns of PUBLISHED "
                        f"BrandKitVersion (id={obj_id}) during archive transition."
                    )

    # ------------------------------------------------------------------
    # 2. Validate Child Models INSERT, UPDATE, and DELETE rules
    # ------------------------------------------------------------------
    for obj in session.new:
        if isinstance(obj, BrandKitVersion):
            initial_status = obj.status

            # SQLAlchemy applies the Python-side column default at INSERT time.
            # Treat an unset status as the effective default: DRAFT.
            if initial_status is None:
                initial_status = BrandKitVersionStatus.DRAFT

            if initial_status not in BrandKitVersionStatus.ALL:
                _raise_immutability_error(
                    f"[P0003] Invalid initial status '{initial_status}' for "
                    f"BrandKitVersion (id={_get_object_id_no_load(obj)}). "
                    f"Permitted statuses are: {', '.join(BrandKitVersionStatus.ALL)}."
                )

            if initial_status != BrandKitVersionStatus.DRAFT:
                _raise_immutability_error(
                    f"[P0003] Initial status for BrandKitVersion "
                    f"(id={_get_object_id_no_load(obj)}) must be DRAFT, "
                    f"got '{initial_status}'."
                )

        elif isinstance(obj, _ALL_VERSION_CHILD_MODELS):
            target_vid, parent_status = _resolve_child_version_id_and_status(obj, use_old=False)
            if parent_status in _PROTECTED_VERSION_STATUSES:
                _raise_immutability_error(
                    f"[P0002] Cannot INSERT child record in {obj.__tablename__} because "
                    f"parent BrandKitVersion (id={target_vid}) is {parent_status} and immutable."
                )

    for obj in session.deleted:
        if isinstance(obj, _ALL_VERSION_CHILD_MODELS):
            state = sa_inspect(obj)
            old_vid, parent_status = _resolve_child_version_id_and_status(obj, use_old=True)
            old_org_id, _ = _get_old_and_new_value(state, "organisation_id")
            if parent_status in _PROTECTED_VERSION_STATUSES and not _is_organisation_being_deleted(old_org_id):
                _raise_immutability_error(
                    f"[P0002] Cannot DELETE child record in {obj.__tablename__} because "
                    f"parent BrandKitVersion (id={old_vid}) is {parent_status} and immutable."
                )

    for obj in session.dirty:
        if isinstance(obj, _ALL_VERSION_CHILD_MODELS) and obj not in session.deleted:
            state = sa_inspect(obj)
            changed_cols = _get_changed_mapped_columns(state)
            if not changed_cols:
                continue

            old_vid, new_vid = _get_old_and_new_value(state, "brand_kit_version_id")
            if _normalize_uuid(old_vid) != _normalize_uuid(new_vid):
                _, old_parent_status = _resolve_child_version_id_and_status(obj, use_old=True)
                if old_parent_status in _PROTECTED_VERSION_STATUSES:
                    _raise_immutability_error(
                        f"[P0002] Cannot move child record out of {old_parent_status} "
                        f"BrandKitVersion (id={old_vid})."
                    )

            target_vid, new_parent_status = _resolve_child_version_id_and_status(obj, use_old=False)
            if new_parent_status in _PROTECTED_VERSION_STATUSES:
                if isinstance(obj, BrandGuidelineDocument):
                    disallowed_cols = changed_cols - ALLOWLISTED_GUIDELINE_DOC_TELEMETRY_COLUMNS
                    if disallowed_cols:
                        _raise_immutability_error(
                            f"[P0002] Cannot modify immutable file identity, ownership, or provenance columns "
                            f"on brand_guideline_documents for {new_parent_status} BrandKitVersion (id={target_vid})."
                        )
                else:
                    _raise_immutability_error(
                        f"[P0002] Cannot UPDATE child record in {obj.__tablename__} because "
                        f"parent BrandKitVersion (id={target_vid}) is {new_parent_status} and immutable."
                    )

    # ------------------------------------------------------------------
    # 3. Validate BrandAuditLog append-only protection
    # ------------------------------------------------------------------
    for obj in session.deleted:
        if isinstance(obj, BrandAuditLog):
            state = sa_inspect(obj)
            obj_id = _get_object_id_no_load(obj)
            old_org_id, _ = _get_old_and_new_value(state, "organisation_id")
            if not _is_organisation_being_deleted(old_org_id):
                _raise_immutability_error(
                    f"[P0005] brand_audit_logs are append-only and cannot be deleted (id={obj_id})."
                )

    for obj in session.dirty:
        if isinstance(obj, BrandAuditLog) and obj not in session.deleted:
            state = sa_inspect(obj)
            obj_id = _get_object_id_no_load(obj)
            changed_cols = _get_changed_mapped_columns(state)
            if not changed_cols:
                continue

            # Allow only FK SET NULL cascade when a draft BrandKitVersion or BrandKit is deleted
            allowed_cascade_cols: set[str] = set()
            old_kit_id, new_kit_id = _get_old_and_new_value(state, "brand_kit_id")
            if new_kit_id is None and _normalize_uuid(old_kit_id) in deleted_kit_ids:
                allowed_cascade_cols.add("brand_kit_id")
            old_ver_id, new_ver_id = _get_old_and_new_value(state, "brand_kit_version_id")
            if new_ver_id is None and _normalize_uuid(old_ver_id) in deleted_version_ids:
                allowed_cascade_cols.add("brand_kit_version_id")

            if changed_cols - allowed_cascade_cols:
                _raise_immutability_error(
                    f"[P0005] brand_audit_logs are append-only and cannot be modified (id={obj_id})."
                )


__all__ = [
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
