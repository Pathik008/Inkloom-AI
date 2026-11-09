"""Domain service for Compliance Rule management inside a Brand Kit version.

Rules are editable only while their parent version is DRAFT; PUBLISHED / ARCHIVED versions are
immutable (also enforced by the ORM listener and PostgreSQL triggers). Every query is scoped to
`organisation_id` and the parent Brand Kit so rule IDs from other tenants are indistinguishable
from non-existent ones (404).
"""
import uuid
from typing import List

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    BrandAuditLog,
    BrandAuditResourceType,
    BrandKitVersion,
    BrandKitVersionStatus,
    ComplianceRule,
    FactRuleApprovalStatus,
    ProvenanceSourceType,
    utcnow,
)
from app.schemas import (
    ComplianceRuleCreateRequest,
    ComplianceRuleUpdateRequest,
)
from app.services import brand_kit_service
from app.services.compliance_engine import RuleDefinitionError, validate_pattern

_RULE_CODE_PREFIX = {
    "PROHIBITED_TERM": "BAN",
    "MANDATORY_DISCLAIMER": "DISC",
    "RESTRICTED_CLAIM": "CLAIM",
    "PRICE_INTEGRITY": "PRICE",
    "TONE_CONSTRAINT": "TONE",
    "MANDATORY_TERMINOLOGY": "TERM",
}
# Changing any of these invalidates a previous approval.
_SUBSTANTIVE_FIELDS = {
    "target_pattern",
    "match_mode",
    "severity",
    "required_disclaimer_text",
    "suggested_replacement",
    "rule_config",
}


def _get_version(db: Session, *, organisation_id, brand_kit_id, version_id) -> BrandKitVersion:
    return brand_kit_service.get_brand_kit_version_or_404(
        db, organisation_id=organisation_id, brand_kit_id=brand_kit_id, version_id=version_id
    )


def _require_draft(version: BrandKitVersion) -> None:
    if version.status != BrandKitVersionStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Rules can only be changed on a DRAFT version; this version is {version.status}. "
            "Create a new draft version to edit rules.",
        )


def _validate_rule_definition(rule_type: str, pattern: str, match_mode: str, config: dict) -> None:
    try:
        validate_pattern(pattern, match_mode)
        trig = (config or {}).get("trigger_pattern")
        if trig:
            validate_pattern(str(trig), (config or {}).get("trigger_match_mode", "CASE_INSENSITIVE"))
    except RuleDefinitionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


def _audit(db: Session, *, version: BrandKitVersion, user_id, action: str, rule: ComplianceRule, details: dict) -> None:
    db.add(
        BrandAuditLog(
            id=uuid.uuid4(),
            organisation_id=version.organisation_id,
            actor_user_id=user_id,
            brand_kit_id=version.brand_kit_id,
            brand_kit_version_id=version.id,
            action=action,
            resource_type=BrandAuditResourceType.RULE,
            resource_id=rule.id,
            details_json={"rule_code": rule.rule_code, **details},
        )
    )


def list_rules(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    rule_type: str | None = None,
    approval_status: str | None = None,
) -> List[ComplianceRule]:
    version = _get_version(db, organisation_id=organisation_id, brand_kit_id=brand_kit_id, version_id=version_id)
    stmt = select(ComplianceRule).where(
        ComplianceRule.brand_kit_version_id == version.id,
        ComplianceRule.organisation_id == organisation_id,
    )
    if rule_type:
        stmt = stmt.where(ComplianceRule.rule_type == rule_type.upper())
    if approval_status:
        stmt = stmt.where(ComplianceRule.approval_status == approval_status.upper())
    stmt = stmt.order_by(ComplianceRule.priority.asc(), ComplianceRule.created_at.asc())
    return list(db.execute(stmt).scalars().all())


def get_rule_or_404(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    rule_id: uuid.UUID,
) -> ComplianceRule:
    version = _get_version(db, organisation_id=organisation_id, brand_kit_id=brand_kit_id, version_id=version_id)
    rule = db.execute(
        select(ComplianceRule).where(
            ComplianceRule.id == rule_id,
            ComplianceRule.brand_kit_version_id == version.id,
            ComplianceRule.organisation_id == organisation_id,
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Compliance rule not found.")
    return rule


def create_rule(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: ComplianceRuleCreateRequest,
) -> ComplianceRule:
    version = _get_version(
        db, organisation_id=organisation_id, brand_kit_id=brand_kit_id, version_id=version_id
    )
    _require_draft(version)
    _validate_rule_definition(payload.rule_type, payload.target_pattern, payload.match_mode, payload.rule_config)

    if payload.rule_type == "MANDATORY_DISCLAIMER" and not (payload.required_disclaimer_text or "").strip():
        # The disclaimer text defaults to the target pattern, which must then be literal text.
        if payload.match_mode == "REGEX":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="required_disclaimer_text is required for a REGEX disclaimer rule.",
            )

    code = payload.rule_code.strip().upper() if payload.rule_code else None
    if code is None:
        prefix = _RULE_CODE_PREFIX[payload.rule_type]
        code = f"{prefix}-{uuid.uuid4().hex[:6].upper()}"
    elif db.execute(
        select(ComplianceRule.id).where(
            ComplianceRule.brand_kit_version_id == version.id, ComplianceRule.rule_code == code
        )
    ).scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Rule code '{code}' already exists in this version."
        )

    rule = ComplianceRule(
        id=uuid.uuid4(),
        brand_kit_version_id=version.id,
        organisation_id=organisation_id,
        rule_code=code,
        rule_type=payload.rule_type,
        priority=payload.priority,
        severity=payload.severity,
        title=payload.title.strip(),
        description=payload.description.strip(),
        target_pattern=payload.target_pattern,
        match_mode=payload.match_mode,
        required_disclaimer_text=payload.required_disclaimer_text,
        suggested_replacement=payload.suggested_replacement,
        rule_config_json=dict(payload.rule_config or {}),
        source_type=ProvenanceSourceType.MANUAL_ENTRY,
        source_reference=payload.source_reference,
        approval_status=FactRuleApprovalStatus.PENDING_REVIEW,
        created_by_user_id=user_id,
        is_active=payload.is_active,
    )
    db.add(rule)
    db.flush()
    _audit(db, version=version, user_id=user_id, action="RULE_CREATED", rule=rule, details={"rule_type": rule.rule_type})
    db.commit()
    db.refresh(rule)
    return rule


def update_rule(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    rule_id: uuid.UUID,
    payload: ComplianceRuleUpdateRequest,
) -> ComplianceRule:
    version = _get_version(db, organisation_id=organisation_id, brand_kit_id=brand_kit_id, version_id=version_id)
    _require_draft(version)
    rule = get_rule_or_404(
        db, organisation_id=organisation_id, brand_kit_id=brand_kit_id, version_id=version_id, rule_id=rule_id
    )
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return rule

    new_pattern = changes.get("target_pattern", rule.target_pattern)
    new_mode = changes.get("match_mode", rule.match_mode)
    new_config = changes.get("rule_config", rule.rule_config_json)
    _validate_rule_definition(rule.rule_type, new_pattern, new_mode, new_config or {})

    for field_name, value in changes.items():
        if field_name == "rule_config":
            rule.rule_config_json = dict(value or {})
        elif value is None and field_name in {"title", "description", "target_pattern", "severity", "match_mode", "priority", "source_reference", "is_active"}:
            continue
        else:
            setattr(rule, field_name, value)

    reset = bool(_SUBSTANTIVE_FIELDS & set(changes)) and rule.approval_status != FactRuleApprovalStatus.PENDING_REVIEW
    if reset:
        rule.approval_status = FactRuleApprovalStatus.PENDING_REVIEW
        rule.reviewed_by_user_id = None
        rule.reviewed_at = None
        rule.review_notes = None
    _audit(
        db,
        version=version,
        user_id=user_id,
        action="RULE_UPDATED",
        rule=rule,
        details={"fields": sorted(changes), "approval_reset": reset},
    )
    db.commit()
    db.refresh(rule)
    return rule


def delete_rule(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    rule_id: uuid.UUID,
) -> None:
    version = _get_version(db, organisation_id=organisation_id, brand_kit_id=brand_kit_id, version_id=version_id)
    _require_draft(version)
    rule = get_rule_or_404(
        db, organisation_id=organisation_id, brand_kit_id=brand_kit_id, version_id=version_id, rule_id=rule_id
    )
    _audit(db, version=version, user_id=user_id, action="RULE_DELETED", rule=rule, details={})
    db.delete(rule)
    db.commit()


def review_rule(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    rule_id: uuid.UUID,
    approve: bool,
    notes: str | None,
) -> ComplianceRule:
    version = _get_version(db, organisation_id=organisation_id, brand_kit_id=brand_kit_id, version_id=version_id)
    _require_draft(version)
    rule = get_rule_or_404(
        db, organisation_id=organisation_id, brand_kit_id=brand_kit_id, version_id=version_id, rule_id=rule_id
    )
    rule.approval_status = FactRuleApprovalStatus.APPROVED if approve else FactRuleApprovalStatus.REJECTED
    rule.reviewed_by_user_id = user_id
    rule.reviewed_at = utcnow()
    rule.review_notes = notes
    _audit(
        db,
        version=version,
        user_id=user_id,
        action="RULE_APPROVED" if approve else "RULE_REJECTED",
        rule=rule,
        details={"notes": notes},
    )
    db.commit()
    db.refresh(rule)
    return rule
