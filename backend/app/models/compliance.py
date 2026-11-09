"""SQLAlchemy ORM models for Phase 4: content submissions, deterministic compliance analyses, and human approvals."""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.brand import JSONBVariant, utcnow


class ComplianceResult:
    PASS = "PASS"
    FAIL = "FAIL"

    ALL = (PASS, FAIL)


class SubmissionStatus:
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"

    ALL = (DRAFT, PENDING_REVIEW, APPROVED, REJECTED, CHANGES_REQUESTED)


class ReviewActionType:
    SUBMIT_FOR_APPROVAL = "SUBMIT_FOR_APPROVAL"
    ASSIGN_REVIEWER = "ASSIGN_REVIEWER"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    COMMENT = "COMMENT"

    ALL = (SUBMIT_FOR_APPROVAL, ASSIGN_REVIEWER, APPROVE, REJECT, REQUEST_CHANGES, COMMENT)


class ContentSubmission(Base):
    """Immutable snapshot of submitted marketing text, bound to a PUBLISHED Brand Kit version.

    Edits and applied corrections create a *new* submission whose `parent_submission_id`
    points at the previous revision, so every analysed text remains auditable.
    """

    __tablename__ = "content_submissions"
    __table_args__ = (
        CheckConstraint("revision_number >= 1", name="ck_content_submissions_revision"),
        Index("ix_content_submissions_org_created", "organisation_id", "created_at"),
        Index("ix_content_submissions_org_status", "organisation_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    brand_kit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("brand_kits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brand_kit_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("brand_kit_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_submission_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("content_submissions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    revision_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    # Human review & approval state
    status: Mapped[str] = mapped_column(String(32), default=SubmissionStatus.DRAFT, nullable=False, index=True)
    assigned_reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_comments: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    submitter: Mapped["User | None"] = relationship("User", foreign_keys=[submitted_by_user_id])
    assigned_reviewer: Mapped["User | None"] = relationship("User", foreign_keys=[assigned_reviewer_id])
    reviewed_by: Mapped["User | None"] = relationship("User", foreign_keys=[reviewed_by_user_id])

    analyses: Mapped[list["ComplianceAnalysis"]] = relationship(
        "ComplianceAnalysis",
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="ComplianceAnalysis.created_at",
    )
    review_actions: Mapped[list["ContentReviewAction"]] = relationship(
        "ContentReviewAction",
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="ContentReviewAction.created_at.asc()",
    )


class ComplianceAnalysis(Base):
    """Persisted deterministic analysis outcome for one ContentSubmission."""

    __tablename__ = "compliance_analyses"
    __table_args__ = (
        CheckConstraint("score BETWEEN 0 AND 100", name="ck_compliance_analyses_score"),
        CheckConstraint("result IN ('PASS', 'FAIL')", name="ck_compliance_analyses_result"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("content_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    brand_kit_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("brand_kit_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(8), nullable=False)
    rules_evaluated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    findings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONBVariant, default=list, nullable=False)
    scoring_json: Mapped[dict[str, Any]] = mapped_column(JSONBVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    submission: Mapped["ContentSubmission"] = relationship("ContentSubmission", back_populates="analyses")


class ContentReviewAction(Base):
    """Audit log and discussion record of human approval actions on a ContentSubmission."""

    __tablename__ = "content_review_actions"
    __table_args__ = (
        Index("ix_content_review_actions_sub_created", "submission_id", "created_at"),
        Index("ix_content_review_actions_org_created", "organisation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("content_submissions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
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
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    submission: Mapped["ContentSubmission"] = relationship("ContentSubmission", back_populates="review_actions")
    actor: Mapped["User | None"] = relationship("User", foreign_keys=[actor_user_id])
