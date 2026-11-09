"""Inkloom AI — Idempotent Judge & Demo Data Seeding Script.

Creates a designated demo organisation, an admin user, a Brand Kit, and an approved,
published version containing realistic financial services compliance rules:
1. BAN-GR: Prohibited term 'guaranteed returns' (CRITICAL)
2. BAN-RF: Prohibited term 'risk-free' (CRITICAL)
3. DISC-RISK: Mandatory disclaimer 'Investments are subject to market risk...' (HIGH)
4. TERM-BRAND: Mandatory terminology 'Acme' (LOW)

This script is strictly opt-in and NOT automatically triggered during production startup.
"""
from __future__ import annotations

import os
import sys
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.database import SessionLocal
from app.models import (
    BrandAuditLog,
    BrandAuditResourceType,
    BrandIdentity,
    BrandKit,
    BrandKitVersion,
    BrandKitVersionStatus,
    ComplianceRule,
    FactRuleApprovalStatus,
    MembershipStatus,
    Organisation,
    OrganisationMembership,
    ProvenanceSourceType,
    RoleName,
    User,
    utcnow,
)
from app.services import brand_kit_service, brand_rule_service
from app.services.organisation_service import get_role_by_name
from app.services.rbac_service import seed_roles_and_permissions


DEMO_ADMIN_EMAIL = os.getenv("DEMO_ADMIN_EMAIL", "judge@inkloom.ai")
DEMO_ADMIN_NAME = os.getenv("DEMO_ADMIN_NAME", "CodeTitans Judge")
DEMO_ADMIN_PASSWORD = os.getenv("DEMO_ADMIN_PASSWORD", "DemoJudge2026!")
DEMO_ORG_NAME = os.getenv("DEMO_ORG_NAME", "Acme Financial Demo")
DEMO_ORG_SLUG = os.getenv("DEMO_ORG_SLUG", "acme-financial-demo")
DEMO_KIT_NAME = "Acme Retail Banking Kit"


def validate_seed_execution_environment() -> None:
    """Ensure demo seeding is strictly opt-in and cannot accidentally run in production."""
    is_production = settings.APP_ENV.lower() in ("production", "staging")
    allow_prod_seed = os.getenv("ALLOW_DEMO_SEED", "").strip().lower() == "true"

    if is_production and not allow_prod_seed:
        raise RuntimeError(
            "Demo seeding is strictly disabled in production and staging environments. "
            "To override for a dedicated staging demo instance, set ALLOW_DEMO_SEED=true "
            "and configure a unique, non-default DEMO_ADMIN_PASSWORD."
        )

    if is_production and DEMO_ADMIN_PASSWORD == "DemoJudge2026!":
        raise ValueError(
            "Insecure default DEMO_ADMIN_PASSWORD detected in production/staging environment. "
            "Configure a secure random password via DEMO_ADMIN_PASSWORD."
        )


def seed_demo_data(db: Session) -> dict[str, Any]:
    """Seed demo data idempotently."""
    validate_seed_execution_environment()
    seed_roles_and_permissions(db)

    # 1. Ensure User
    user = db.execute(select(User).where(User.email == DEMO_ADMIN_EMAIL.lower())).scalar_one_or_none()
    if user is None:
        user = User(
            id=uuid.uuid4(),
            full_name=DEMO_ADMIN_NAME,
            email=DEMO_ADMIN_EMAIL.lower(),
            password_hash=hash_password(DEMO_ADMIN_PASSWORD),
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        db.flush()
        print(f"[DEMO SEED] Created admin user: {user.email}")
    else:
        # Update password to ensure it matches current DEMO_ADMIN_PASSWORD
        user.password_hash = hash_password(DEMO_ADMIN_PASSWORD)
        user.is_active = True
        user.is_verified = True
        db.flush()
        print(f"[DEMO SEED] Existing user found and credentials verified: {user.email}")

    # 2. Ensure Organisation
    org = db.execute(select(Organisation).where(Organisation.slug == DEMO_ORG_SLUG)).scalar_one_or_none()
    if org is None:
        org = Organisation(
            id=uuid.uuid4(),
            name=DEMO_ORG_NAME,
            slug=DEMO_ORG_SLUG,
            created_by=user.id,
        )
        db.add(org)
        db.flush()
        print(f"[DEMO SEED] Created organisation: {org.name} ({org.slug})")
    else:
        print(f"[DEMO SEED] Existing organisation found: {org.name}")

    # 3. Ensure Membership
    admin_role = get_role_by_name(db, RoleName.ADMIN)
    membership = db.execute(
        select(OrganisationMembership).where(
            OrganisationMembership.user_id == user.id,
            OrganisationMembership.organisation_id == org.id,
        )
    ).scalar_one_or_none()
    if membership is None:
        membership = OrganisationMembership(
            id=uuid.uuid4(),
            user_id=user.id,
            organisation_id=org.id,
            role_id=admin_role.id,
            status=MembershipStatus.ACTIVE,
        )
        db.add(membership)
        db.flush()
        print(f"[DEMO SEED] Associated user {user.email} as ADMIN of {org.name}")
    else:
        membership.status = MembershipStatus.ACTIVE
        membership.role_id = admin_role.id
        db.flush()

    # 4. Ensure Brand Kit
    kit = db.execute(
        select(BrandKit).where(
            BrandKit.organisation_id == org.id,
            BrandKit.name == DEMO_KIT_NAME,
        )
    ).scalar_one_or_none()

    if kit is None:
        from app.schemas import BrandIdentityCreateRequest, BrandKitCreateRequest
        kit = brand_kit_service.create_brand_kit(
            db,
            organisation_id=org.id,
            user_id=user.id,
            payload=BrandKitCreateRequest(
                name=DEMO_KIT_NAME,
                slug="acme-retail-banking",
                description="Official corporate brand kit for Acme Retail Banking, mutual funds, and customer communications.",
                industry="Financial Services",
                identity=BrandIdentityCreateRequest(
                    brand_name="Acme",
                    tagline="Secure, Transparent Financial Futures",
                    primary_color_hex="#0052CC",
                    preferred_vocabulary=["Acme", "potential returns", "lower-risk", "financial goals"],
                    prohibited_vocabulary=["guaranteed returns", "risk-free", "100% safe", "get rich quick"],
                ),
            ),
        )
        print(f"[DEMO SEED] Created Brand Kit: {kit.name}")

    # 5. Check if there is already a published version
    published_ver = db.execute(
        select(BrandKitVersion).where(
            BrandKitVersion.brand_kit_id == kit.id,
            BrandKitVersion.organisation_id == org.id,
            BrandKitVersion.status == BrandKitVersionStatus.PUBLISHED,
        )
    ).scalar_one_or_none()

    if published_ver is not None:
        print(f"[DEMO SEED] Published version already active: Version {published_ver.version_number}")
        active_ver = published_ver
    else:
        # Get latest DRAFT version
        draft_ver = db.execute(
            select(BrandKitVersion).where(
                BrandKitVersion.brand_kit_id == kit.id,
                BrandKitVersion.organisation_id == org.id,
                BrandKitVersion.status == BrandKitVersionStatus.DRAFT,
            )
        ).scalar_one_or_none()

        if draft_ver is None:
            from app.schemas import BrandKitVersionCreateRequest
            draft_ver = brand_kit_service.create_draft_version(
                db,
                organisation_id=org.id,
                user_id=user.id,
                brand_kit_id=kit.id,
                payload=BrandKitVersionCreateRequest(changelog="Initial demo compliance rules draft"),
            )

        # Ensure Rules on draft_ver
        demo_rules = [
            {
                "rule_code": "BAN-GR",
                "rule_type": "PROHIBITED_TERM",
                "title": "Guaranteed Returns Prohibition",
                "description": "Financial regulations strictly prohibit promising or implying guaranteed returns on investments.",
                "target_pattern": "guaranteed returns",
                "severity": "CRITICAL",
                "match_mode": "CASE_INSENSITIVE",
                "suggested_replacement": "potential returns",
                "priority": 10,
            },
            {
                "rule_code": "BAN-RF",
                "rule_type": "PROHIBITED_TERM",
                "title": "Risk-Free Claims Prohibition",
                "description": "Financial and investment products cannot be marketed as risk-free.",
                "target_pattern": "risk-free",
                "severity": "CRITICAL",
                "match_mode": "CASE_INSENSITIVE",
                "suggested_replacement": "lower-risk",
                "priority": 20,
            },
            {
                "rule_code": "DISC-RISK",
                "rule_type": "MANDATORY_DISCLAIMER",
                "title": "Market Risk Mandatory Disclaimer",
                "description": "All investment marketing copy must include the official mandatory risk statement.",
                "target_pattern": "market risk",
                "required_disclaimer_text": "Investments are subject to market risk. Read all scheme related documents carefully.",
                "severity": "HIGH",
                "match_mode": "CASE_INSENSITIVE",
                "priority": 30,
            },
            {
                "rule_code": "TERM-BRAND",
                "rule_type": "MANDATORY_TERMINOLOGY",
                "title": "Official Brand Name Requirement",
                "description": "All public marketing copy must explicitly reference the Acme brand.",
                "target_pattern": "Acme",
                "suggested_replacement": "Acme",
                "severity": "LOW",
                "match_mode": "EXACT",
                "priority": 40,
            },
        ]

        from app.schemas import ComplianceRuleCreateRequest
        for r_spec in demo_rules:
            existing_rule = db.execute(
                select(ComplianceRule).where(
                    ComplianceRule.brand_kit_version_id == draft_ver.id,
                    ComplianceRule.rule_code == r_spec["rule_code"],
                )
            ).scalar_one_or_none()
            if existing_rule is None:
                new_rule = brand_rule_service.create_rule(
                    db,
                    organisation_id=org.id,
                    user_id=user.id,
                    brand_kit_id=kit.id,
                    version_id=draft_ver.id,
                    payload=ComplianceRuleCreateRequest(
                        rule_code=r_spec["rule_code"],
                        rule_type=r_spec["rule_type"],
                        title=r_spec["title"],
                        description=r_spec["description"],
                        target_pattern=r_spec["target_pattern"],
                        severity=r_spec["severity"],
                        match_mode=r_spec["match_mode"],
                        suggested_replacement=r_spec.get("suggested_replacement"),
                        required_disclaimer_text=r_spec.get("required_disclaimer_text"),
                        priority=r_spec["priority"],
                        source_reference="SEBI & FTC Marketing Compliance Guidelines",
                    ),
                )
                # Approve immediately for demo
                brand_rule_service.review_rule(
                    db,
                    organisation_id=org.id,
                    user_id=user.id,
                    brand_kit_id=kit.id,
                    version_id=draft_ver.id,
                    rule_id=new_rule.id,
                    approve=True,
                    notes="Approved during demo environment provisioning.",
                )
                print(f"[DEMO SEED] Created & Approved rule {r_spec['rule_code']}")

        # Publish the draft version
        published_ver = brand_kit_service.publish_version(
            db,
            organisation_id=org.id,
            user_id=user.id,
            brand_kit_id=kit.id,
            version_id=draft_ver.id,
        )
        print(f"[DEMO SEED] Version {published_ver.version_number} published successfully!")
        active_ver = published_ver

    db.commit()

    return {
        "status": "ready",
        "organisation_id": str(org.id),
        "organisation_name": org.name,
        "organisation_slug": org.slug,
        "admin_email": user.email,
        "admin_password": "[REDACTED]",
        "brand_kit_id": str(kit.id),
        "brand_kit_name": kit.name,
        "published_version_id": str(active_ver.id),
        "published_version_number": active_ver.version_number,
    }


if __name__ == "__main__":
    db = SessionLocal()
    try:
        res = seed_demo_data(db)
        print("\n" + "=" * 65)
        print(" INKLOOM AI — JUDGE DEMO SEED COMPLETED")
        print("=" * 65)
        print(f" Organisation:  {res['organisation_name']} (ID: {res['organisation_id']})")
        print(f" Login Email:   {res['admin_email']}")
        print(" Login Pass:    [REDACTED — Check DEMO_ADMIN_PASSWORD environment setting]")
        print(f" Brand Kit:     {res['brand_kit_name']} (ID: {res['brand_kit_id']})")
        print(f" Active Vers:   v{res['published_version_number']} (PUBLISHED)")
        print("=" * 65 + "\n")
    finally:
        db.close()
