"""Compliance rule management routes (scoped to a Brand Kit version)."""
import uuid
from typing import List

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import TenantContext, require_permission
from app.database import get_db
from app.models import PermissionCode
from app.schemas import (
    ComplianceRuleCreateRequest,
    ComplianceRuleResponse,
    ComplianceRuleReviewRequest,
    ComplianceRuleUpdateRequest,
)
from app.services import brand_rule_service

router = APIRouter()


@router.get("", response_model=List[ComplianceRuleResponse], summary="List rules of a Brand Kit version")
def list_rules(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    rule_type: str | None = Query(default=None),
    approval_status: str | None = Query(default=None),
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_READ)),
    db: Session = Depends(get_db),
):
    rules = brand_rule_service.list_rules(
        db,
        organisation_id=context.organisation.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        rule_type=rule_type,
        approval_status=approval_status,
    )
    return [ComplianceRuleResponse.model_validate(r) for r in rules]


@router.post(
    "",
    response_model=ComplianceRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a compliance rule (banned phrase, disclaimer, terminology, ...) on a DRAFT version",
)
def create_rule(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: ComplianceRuleCreateRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_MANAGE)),
    db: Session = Depends(get_db),
):
    rule = brand_rule_service.create_rule(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        payload=payload,
    )
    return ComplianceRuleResponse.model_validate(rule)


@router.get("/{rule_id}", response_model=ComplianceRuleResponse, summary="Get a compliance rule")
def get_rule(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    rule_id: uuid.UUID,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_READ)),
    db: Session = Depends(get_db),
):
    rule = brand_rule_service.get_rule_or_404(
        db,
        organisation_id=context.organisation.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        rule_id=rule_id,
    )
    return ComplianceRuleResponse.model_validate(rule)


@router.patch("/{rule_id}", response_model=ComplianceRuleResponse, summary="Update a rule on a DRAFT version")
def update_rule(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    rule_id: uuid.UUID,
    payload: ComplianceRuleUpdateRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_MANAGE)),
    db: Session = Depends(get_db),
):
    rule = brand_rule_service.update_rule(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        rule_id=rule_id,
        payload=payload,
    )
    return ComplianceRuleResponse.model_validate(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a rule on a DRAFT version")
def delete_rule(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    rule_id: uuid.UUID,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_MANAGE)),
    db: Session = Depends(get_db),
):
    brand_rule_service.delete_rule(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        rule_id=rule_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{rule_id}/approve", response_model=ComplianceRuleResponse, summary="Approve a rule")
def approve_rule(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    rule_id: uuid.UUID,
    payload: ComplianceRuleReviewRequest | None = None,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_MANAGE)),
    db: Session = Depends(get_db),
):
    rule = brand_rule_service.review_rule(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        rule_id=rule_id,
        approve=True,
        notes=payload.notes if payload else None,
    )
    return ComplianceRuleResponse.model_validate(rule)


@router.post("/{rule_id}/reject", response_model=ComplianceRuleResponse, summary="Reject a rule")
def reject_rule(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    rule_id: uuid.UUID,
    payload: ComplianceRuleReviewRequest | None = None,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_MANAGE)),
    db: Session = Depends(get_db),
):
    rule = brand_rule_service.review_rule(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        rule_id=rule_id,
        approve=False,
        notes=payload.notes if payload else None,
    )
    return ComplianceRuleResponse.model_validate(rule)
