"""Domain service for Brand Kit management and version lifecycle.

Enforces organisation-scoped multi-tenancy, sequential version numbering,
deep-copy cloning, pre-publish gates, and immutable state transitions.
"""
import re
import uuid
from typing import List

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    ApprovedBrandFact,
    BrandAsset,
    BrandAuditLog,
    BrandAuditResourceType,
    BrandDocumentChunk,
    BrandGuidelineDocument,
    BrandIdentity,
    BrandKit,
    BrandKitVersion,
    BrandKitVersionStatus,
    ComplianceRule,
    DocumentParsingStatus,
    FactRuleApprovalStatus,
    Organisation,
    utcnow,
)
from app.schemas import (
    BrandKitCreateRequest,
    BrandKitUpdateRequest,
    BrandKitVersionCreateRequest,
    BrandKitVersionUpdateRequest,
)


def generate_brand_kit_slug(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    name: str,
    requested_slug: str | None = None,
) -> str:
    """Create a URL-safe, organisation-unique slug for a Brand Kit."""
    if requested_slug:
        base = re.sub(r"[^a-z0-9]+", "-", requested_slug.strip().lower()).strip("-")
    else:
        base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")

    if not base:
        base = "brand-kit"
    base = base[:140]

    candidate = base
    counter = 1
    while (
        db.execute(
            select(BrandKit.id).where(
                BrandKit.organisation_id == organisation_id,
                BrandKit.slug == candidate,
            )
        ).scalar_one_or_none()
        is not None
    ):
        counter += 1
        candidate = f"{base}-{counter}"
    return candidate


def create_brand_kit(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: BrandKitCreateRequest,
) -> BrandKit:
    """Create a new Brand Kit with sequential DRAFT Version 1 and initial BrandIdentity."""
    org = db.execute(
        select(Organisation.id).where(Organisation.id == organisation_id)
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation not found.",
        )

    slug = generate_brand_kit_slug(
        db,
        organisation_id=organisation_id,
        name=payload.name,
        requested_slug=payload.slug,
    )

    kit = BrandKit(
        id=uuid.uuid4(),
        organisation_id=organisation_id,
        name=payload.name,
        slug=slug,
        description=payload.description,
        industry=payload.industry,
        is_archived=False,
        created_by_user_id=user_id,
    )
    db.add(kit)
    db.flush()

    ver = BrandKitVersion(
        id=uuid.uuid4(),
        brand_kit_id=kit.id,
        organisation_id=organisation_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        changelog="Initial draft version",
        created_by_user_id=user_id,
    )
    db.add(ver)
    db.flush()

    ident_data = payload.identity
    identity = BrandIdentity(
        id=uuid.uuid4(),
        brand_kit_version_id=ver.id,
        organisation_id=organisation_id,
        brand_name=(ident_data.brand_name if ident_data and ident_data.brand_name else kit.name),
        tagline=ident_data.tagline if ident_data else None,
        mission_statement=ident_data.mission_statement if ident_data else None,
        brand_voice_tone=ident_data.brand_voice_tone if ident_data else None,
        brand_voice_guidelines=ident_data.brand_voice_guidelines if ident_data else None,
        preferred_vocabulary_json=list(ident_data.preferred_vocabulary) if ident_data and ident_data.preferred_vocabulary else [],
        prohibited_vocabulary_json=list(ident_data.prohibited_vocabulary) if ident_data and ident_data.prohibited_vocabulary else [],
        color_palette_json=[dict(c) for c in ident_data.color_palette] if ident_data and ident_data.color_palette else [],
        typography_rules_json=dict(ident_data.typography_rules) if ident_data and ident_data.typography_rules else {},
        primary_color_hex=ident_data.primary_color_hex if ident_data else None,
        secondary_color_hex=ident_data.secondary_color_hex if ident_data else None,
        accent_color_hex=ident_data.accent_color_hex if ident_data else None,
        neutral_light_hex=ident_data.neutral_light_hex if ident_data else None,
        neutral_dark_hex=ident_data.neutral_dark_hex if ident_data else None,
        primary_font_family=ident_data.primary_font_family if ident_data else None,
        secondary_font_family=ident_data.secondary_font_family if ident_data else None,
        updated_by_user_id=user_id,
    )
    db.add(identity)
    db.flush()

    audit = BrandAuditLog(
        id=uuid.uuid4(),
        organisation_id=organisation_id,
        actor_user_id=user_id,
        brand_kit_id=kit.id,
        brand_kit_version_id=ver.id,
        action="BRAND_KIT_CREATED",
        resource_type=BrandAuditResourceType.BRAND_KIT,
        resource_id=kit.id,
        details_json={"name": kit.name, "slug": kit.slug, "version_number": 1},
    )
    db.add(audit)
    db.commit()
    db.refresh(kit)
    return kit


def list_brand_kits(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    include_archived: bool = False,
) -> List[BrandKit]:
    """Return all Brand Kits belonging to the target organisation."""
    stmt = select(BrandKit).where(BrandKit.organisation_id == organisation_id)
    if not include_archived:
        stmt = stmt.where(BrandKit.is_archived.is_(False))
    stmt = stmt.order_by(BrandKit.created_at.desc())
    return list(db.execute(stmt).scalars().all())


def get_brand_kit_or_404(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    for_update: bool = False,
) -> BrandKit:
    """Retrieve a Brand Kit strictly scoped to organisation_id."""
    stmt = select(BrandKit).where(
        BrandKit.id == brand_kit_id,
        BrandKit.organisation_id == organisation_id,
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    kit = db.execute(stmt).scalar_one_or_none()
    if not kit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Brand Kit not found in this organisation.",
        )
    return kit


def update_brand_kit(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    payload: BrandKitUpdateRequest,
) -> BrandKit:
    """Update Brand Kit container metadata."""
    kit = get_brand_kit_or_404(
        db,
        organisation_id=organisation_id,
        brand_kit_id=brand_kit_id,
        for_update=True,
    )

    if payload.name is not None:
        kit.name = payload.name

    if payload.slug is not None and payload.slug != kit.slug:
        kit.slug = generate_brand_kit_slug(
            db,
            organisation_id=organisation_id,
            name=kit.name,
            requested_slug=payload.slug,
        )

    if payload.description is not None:
        kit.description = payload.description

    if payload.industry is not None:
        kit.industry = payload.industry

    if payload.is_archived is not None:
        kit.is_archived = payload.is_archived

    kit.updated_at = utcnow()

    audit = BrandAuditLog(
        id=uuid.uuid4(),
        organisation_id=organisation_id,
        actor_user_id=user_id,
        brand_kit_id=kit.id,
        action="BRAND_KIT_UPDATED",
        resource_type=BrandAuditResourceType.BRAND_KIT,
        resource_id=kit.id,
        details_json={
            "updated_fields": [k for k, v in payload.model_dump(exclude_unset=True).items()]
        },
    )
    db.add(audit)
    db.commit()
    db.refresh(kit)
    return kit


def get_brand_kit_version_or_404(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    for_update: bool = False,
) -> BrandKitVersion:
    """Retrieve a BrandKitVersion strictly scoped to brand_kit_id and organisation_id."""
    stmt = select(BrandKitVersion).where(
        BrandKitVersion.id == version_id,
        BrandKitVersion.brand_kit_id == brand_kit_id,
        BrandKitVersion.organisation_id == organisation_id,
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    version = db.execute(stmt).scalar_one_or_none()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Brand Kit version not found in this organisation.",
        )
    return version


def create_draft_version(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    payload: BrandKitVersionCreateRequest | None = None,
) -> BrandKitVersion:
    """Create a new sequential DRAFT version by deep-copying content from source/active version."""
    kit = get_brand_kit_or_404(
        db,
        organisation_id=organisation_id,
        brand_kit_id=brand_kit_id,
        for_update=True,
    )

    # Enforce single-DRAFT invariant defensively before hitting DB partial unique index
    existing_draft = db.execute(
        select(BrandKitVersion).where(
            BrandKitVersion.brand_kit_id == brand_kit_id,
            BrandKitVersion.organisation_id == organisation_id,
            BrandKitVersion.status == BrandKitVersionStatus.DRAFT,
        )
    ).scalar_one_or_none()

    if existing_draft is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Brand Kit already has a DRAFT version (v{existing_draft.version_number}). "
                "Only one DRAFT version is permitted per Brand Kit at a time. "
                "Publish or delete the existing draft before creating a new one."
            ),
        )

    max_ver = db.execute(
        select(func.max(BrandKitVersion.version_number)).where(
            BrandKitVersion.brand_kit_id == brand_kit_id,
            BrandKitVersion.organisation_id == organisation_id,
        )
    ).scalar_one() or 0
    next_version_number = max_ver + 1

    source_ver: BrandKitVersion | None = None
    if payload and payload.source_version_id:
        source_ver = get_brand_kit_version_or_404(
            db,
            organisation_id=organisation_id,
            brand_kit_id=brand_kit_id,
            version_id=payload.source_version_id,
        )
    elif kit.active_version_id:
        source_ver = get_brand_kit_version_or_404(
            db,
            organisation_id=organisation_id,
            brand_kit_id=brand_kit_id,
            version_id=kit.active_version_id,
        )
    else:
        source_ver = db.execute(
            select(BrandKitVersion)
            .where(
                BrandKitVersion.brand_kit_id == brand_kit_id,
                BrandKitVersion.organisation_id == organisation_id,
            )
            .order_by(BrandKitVersion.version_number.desc())
        ).scalars().first()

    new_ver = BrandKitVersion(
        id=uuid.uuid4(),
        brand_kit_id=brand_kit_id,
        organisation_id=organisation_id,
        version_number=next_version_number,
        status=BrandKitVersionStatus.DRAFT,
        changelog=payload.changelog if payload else None,
        cloned_from_version_id=source_ver.id if source_ver else None,
        created_by_user_id=user_id,
    )
    db.add(new_ver)
    db.flush()

    if source_ver is not None:
        if source_ver.identity is not None:
            new_ident = BrandIdentity(
                id=uuid.uuid4(),
                brand_kit_version_id=new_ver.id,
                organisation_id=organisation_id,
                brand_name=source_ver.identity.brand_name,
                tagline=source_ver.identity.tagline,
                mission_statement=source_ver.identity.mission_statement,
                brand_voice_tone=source_ver.identity.brand_voice_tone,
                brand_voice_guidelines=source_ver.identity.brand_voice_guidelines,
                preferred_vocabulary_json=list(source_ver.identity.preferred_vocabulary_json or []),
                prohibited_vocabulary_json=list(source_ver.identity.prohibited_vocabulary_json or []),
                color_palette_json=[dict(c) for c in (source_ver.identity.color_palette_json or [])],
                typography_rules_json=dict(source_ver.identity.typography_rules_json or {}),
                primary_color_hex=source_ver.identity.primary_color_hex,
                secondary_color_hex=source_ver.identity.secondary_color_hex,
                accent_color_hex=source_ver.identity.accent_color_hex,
                neutral_light_hex=source_ver.identity.neutral_light_hex,
                neutral_dark_hex=source_ver.identity.neutral_dark_hex,
                primary_font_family=source_ver.identity.primary_font_family,
                secondary_font_family=source_ver.identity.secondary_font_family,
                updated_by_user_id=user_id,
            )
            db.add(new_ident)

        for fact in source_ver.facts:
            if fact.is_active:
                new_fact = ApprovedBrandFact(
                    id=uuid.uuid4(),
                    brand_kit_version_id=new_ver.id,
                    organisation_id=organisation_id,
                    category=fact.category,
                    subject_name=fact.subject_name,
                    fact_key=fact.fact_key,
                    fact_value=fact.fact_value,
                    currency=fact.currency,
                    numeric_value=fact.numeric_value,
                    unit=fact.unit,
                    source_type=fact.source_type,
                    source_reference=fact.source_reference,
                    evidence_excerpt=fact.evidence_excerpt,
                    approval_status=fact.approval_status,
                    is_active=fact.is_active,
                    effective_from=fact.effective_from,
                    effective_to=fact.effective_to,
                    created_by_user_id=user_id,
                )
                db.add(new_fact)

        for rule in source_ver.rules:
            if rule.is_active:
                new_rule = ComplianceRule(
                    id=uuid.uuid4(),
                    brand_kit_version_id=new_ver.id,
                    organisation_id=organisation_id,
                    rule_code=rule.rule_code,
                    rule_type=rule.rule_type,
                    priority=rule.priority,
                    severity=rule.severity,
                    title=rule.title,
                    description=rule.description,
                    target_pattern=rule.target_pattern,
                    match_mode=rule.match_mode,
                    required_disclaimer_text=rule.required_disclaimer_text,
                    suggested_replacement=rule.suggested_replacement,
                    rule_config_json=dict(rule.rule_config_json or {}),
                    source_type=rule.source_type,
                    source_reference=rule.source_reference,
                    evidence_excerpt=rule.evidence_excerpt,
                    approval_status=rule.approval_status,
                    is_active=rule.is_active,
                    effective_from=rule.effective_from,
                    effective_to=rule.effective_to,
                    created_by_user_id=user_id,
                )
                db.add(new_rule)

        for asset in source_ver.assets:
            new_asset = BrandAsset(
                id=uuid.uuid4(),
                brand_kit_version_id=new_ver.id,
                organisation_id=organisation_id,
                asset_type=asset.asset_type,
                title=asset.title,
                description=asset.description,
                original_filename=asset.original_filename,
                stored_filename=asset.stored_filename,
                storage_backend=asset.storage_backend,
                storage_path=asset.storage_path,
                mime_type=asset.mime_type,
                file_size_bytes=asset.file_size_bytes,
                file_sha256=asset.file_sha256,
                image_width=asset.image_width,
                image_height=asset.image_height,
                asset_metadata_json=dict(asset.asset_metadata_json or {}),
                uploaded_by_user_id=user_id,
            )
            db.add(new_asset)

        for doc in source_ver.documents:
            new_doc = BrandGuidelineDocument(
                id=uuid.uuid4(),
                brand_kit_version_id=new_ver.id,
                organisation_id=organisation_id,
                title=doc.title,
                document_category=doc.document_category,
                original_filename=doc.original_filename,
                stored_filename=doc.stored_filename,
                storage_backend=doc.storage_backend,
                storage_path=doc.storage_path,
                mime_type=doc.mime_type,
                file_size_bytes=doc.file_size_bytes,
                file_sha256=doc.file_sha256,
                page_count=doc.page_count,
                parsing_status=doc.parsing_status,
                parse_attempt_count=doc.parse_attempt_count,
                last_error_code=doc.last_error_code,
                last_error_message=doc.last_error_message,
                raw_text_content=doc.raw_text_content,
                embedding_model=doc.embedding_model,
                embedding_model_version=doc.embedding_model_version,
                parsed_at=doc.parsed_at,
                embedded_at=doc.embedded_at,
                uploaded_by_user_id=user_id,
            )
            db.add(new_doc)
            db.flush()

            for chunk in doc.chunks:
                new_chunk = BrandDocumentChunk(
                    id=uuid.uuid4(),
                    document_id=new_doc.id,
                    brand_kit_version_id=new_ver.id,
                    organisation_id=organisation_id,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number,
                    section_heading=chunk.section_heading,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    content=chunk.content,
                    content_sha256=chunk.content_sha256,
                    token_count=chunk.token_count,
                    embedding=chunk.embedding,
                    embedding_model=chunk.embedding_model,
                    embedding_model_version=chunk.embedding_model_version,
                    embedding_dimension=chunk.embedding_dimension,
                    metadata_json=dict(chunk.metadata_json or {}) if chunk.metadata_json else None,
                )
                db.add(new_chunk)
    else:
        db.add(
            BrandIdentity(
                id=uuid.uuid4(),
                brand_kit_version_id=new_ver.id,
                organisation_id=organisation_id,
                brand_name=kit.name,
                updated_by_user_id=user_id,
            )
        )

    audit = BrandAuditLog(
        id=uuid.uuid4(),
        organisation_id=organisation_id,
        actor_user_id=user_id,
        brand_kit_id=brand_kit_id,
        brand_kit_version_id=new_ver.id,
        action="VERSION_CREATED",
        resource_type=BrandAuditResourceType.VERSION,
        resource_id=new_ver.id,
        details_json={
            "version_number": new_ver.version_number,
            "cloned_from": str(source_ver.id) if source_ver else None,
        },
    )
    db.add(audit)
    db.commit()
    db.refresh(new_ver)
    return new_ver


def update_draft_version(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: BrandKitVersionUpdateRequest,
) -> BrandKitVersion:
    """Update changelog or 1:1 BrandIdentity for a DRAFT version."""
    version = get_brand_kit_version_or_404(
        db,
        organisation_id=organisation_id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        for_update=True,
    )

    if version.status != BrandKitVersionStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Brand Kit version {version.version_number} is {version.status} "
                "and strictly immutable. Create a new draft version to make changes."
            ),
        )

    if payload.changelog is not None:
        version.changelog = payload.changelog

    if payload.identity is not None:
        ident = version.identity
        if ident is None:
            ident = BrandIdentity(
                id=uuid.uuid4(),
                brand_kit_version_id=version.id,
                organisation_id=organisation_id,
                brand_name="Brand Identity",
            )
            db.add(ident)

        i_data = payload.identity
        if i_data.brand_name is not None:
            ident.brand_name = i_data.brand_name
        if i_data.tagline is not None:
            ident.tagline = i_data.tagline
        if i_data.mission_statement is not None:
            ident.mission_statement = i_data.mission_statement
        if i_data.brand_voice_tone is not None:
            ident.brand_voice_tone = i_data.brand_voice_tone
        if i_data.brand_voice_guidelines is not None:
            ident.brand_voice_guidelines = i_data.brand_voice_guidelines
        if i_data.preferred_vocabulary:
            ident.preferred_vocabulary_json = list(i_data.preferred_vocabulary)
        if i_data.prohibited_vocabulary:
            ident.prohibited_vocabulary_json = list(i_data.prohibited_vocabulary)
        if i_data.color_palette:
            ident.color_palette_json = [dict(c) for c in i_data.color_palette]
        if i_data.typography_rules:
            ident.typography_rules_json = dict(i_data.typography_rules)
        if i_data.primary_color_hex is not None:
            ident.primary_color_hex = i_data.primary_color_hex
        if i_data.secondary_color_hex is not None:
            ident.secondary_color_hex = i_data.secondary_color_hex
        if i_data.accent_color_hex is not None:
            ident.accent_color_hex = i_data.accent_color_hex
        if i_data.neutral_light_hex is not None:
            ident.neutral_light_hex = i_data.neutral_light_hex
        if i_data.neutral_dark_hex is not None:
            ident.neutral_dark_hex = i_data.neutral_dark_hex
        if i_data.primary_font_family is not None:
            ident.primary_font_family = i_data.primary_font_family
        if i_data.secondary_font_family is not None:
            ident.secondary_font_family = i_data.secondary_font_family

        ident.updated_by_user_id = user_id
        ident.updated_at = utcnow()

    version.updated_at = utcnow()

    audit = BrandAuditLog(
        id=uuid.uuid4(),
        organisation_id=organisation_id,
        actor_user_id=user_id,
        brand_kit_id=brand_kit_id,
        brand_kit_version_id=version.id,
        action="VERSION_UPDATED",
        resource_type=BrandAuditResourceType.VERSION,
        resource_id=version.id,
        details_json={"version_number": version.version_number},
    )
    db.add(audit)
    db.commit()
    db.refresh(version)
    return version


def publish_version(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
) -> BrandKitVersion:
    """Validate pre-publish gates and atomically publish a DRAFT version.

    Supersedes any existing PUBLISHED version to ARCHIVED and sets active_version_id.
    """
    kit = get_brand_kit_or_404(
        db,
        organisation_id=organisation_id,
        brand_kit_id=brand_kit_id,
        for_update=True,
    )
    version = get_brand_kit_version_or_404(
        db,
        organisation_id=organisation_id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        for_update=True,
    )

    if version.status != BrandKitVersionStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only DRAFT versions can be published. Current version status is '{version.status}'.",
        )

    # Pre-publish gate 1: all facts must be approved
    unapproved_facts = db.execute(
        select(func.count(ApprovedBrandFact.id)).where(
            ApprovedBrandFact.brand_kit_version_id == version_id,
            ApprovedBrandFact.approval_status != FactRuleApprovalStatus.APPROVED,
        )
    ).scalar_one() or 0
    if unapproved_facts > 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Cannot publish version: {unapproved_facts} brand fact(s) are pending review or rejected.",
        )

    # Pre-publish gate 2: all rules must be approved
    unapproved_rules = db.execute(
        select(func.count(ComplianceRule.id)).where(
            ComplianceRule.brand_kit_version_id == version_id,
            ComplianceRule.approval_status != FactRuleApprovalStatus.APPROVED,
        )
    ).scalar_one() or 0
    if unapproved_rules > 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Cannot publish version: {unapproved_rules} compliance rule(s) are pending review or rejected.",
        )

    # Pre-publish gate 3: all guideline documents must be fully embedded
    incomplete_docs = db.execute(
        select(func.count(BrandGuidelineDocument.id)).where(
            BrandGuidelineDocument.brand_kit_version_id == version_id,
            BrandGuidelineDocument.parsing_status != DocumentParsingStatus.EMBEDDED,
        )
    ).scalar_one() or 0
    if incomplete_docs > 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Cannot publish version: {incomplete_docs} guideline document(s) have not completed embedding.",
        )

    # Supersede previously published version (if any) to ARCHIVED
    current_published = db.execute(
        select(BrandKitVersion)
        .where(
            BrandKitVersion.brand_kit_id == brand_kit_id,
            BrandKitVersion.organisation_id == organisation_id,
            BrandKitVersion.status == BrandKitVersionStatus.PUBLISHED,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()

    if current_published is not None:
        current_published.status = BrandKitVersionStatus.ARCHIVED
        current_published.archived_at = utcnow()
        current_published.archived_by_user_id = user_id
        db.flush()

    # Atomically promote target draft to PUBLISHED
    version.status = BrandKitVersionStatus.PUBLISHED
    version.published_at = utcnow()
    version.published_by_user_id = user_id
    db.flush()

    # Bind active version on parent BrandKit
    kit.active_version_id = version.id
    kit.updated_at = utcnow()
    db.flush()

    audit = BrandAuditLog(
        id=uuid.uuid4(),
        organisation_id=organisation_id,
        actor_user_id=user_id,
        brand_kit_id=brand_kit_id,
        brand_kit_version_id=version.id,
        action="VERSION_PUBLISHED",
        resource_type=BrandAuditResourceType.VERSION,
        resource_id=version.id,
        details_json={
            "version_number": version.version_number,
            "superseded_version_id": str(current_published.id) if current_published else None,
        },
    )
    db.add(audit)
    db.commit()
    db.refresh(version)
    return version


def archive_version(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
) -> BrandKitVersion:
    """Atomically archive a PUBLISHED version and clear active_version_id if active."""
    kit = get_brand_kit_or_404(
        db,
        organisation_id=organisation_id,
        brand_kit_id=brand_kit_id,
        for_update=True,
    )
    version = get_brand_kit_version_or_404(
        db,
        organisation_id=organisation_id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        for_update=True,
    )

    if version.status == BrandKitVersionStatus.ARCHIVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Brand Kit version {version.version_number} is already ARCHIVED.",
        )
    if version.status == BrandKitVersionStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A DRAFT version cannot be archived directly. It must be published first, or deleted.",
        )
    if version.status != BrandKitVersionStatus.PUBLISHED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot archive version with status '{version.status}'. Only PUBLISHED versions can be archived.",
        )

    version.status = BrandKitVersionStatus.ARCHIVED
    version.archived_at = utcnow()
    version.archived_by_user_id = user_id
    db.flush()

    if kit.active_version_id == version.id:
        kit.active_version_id = None
        kit.updated_at = utcnow()
        db.flush()

    audit = BrandAuditLog(
        id=uuid.uuid4(),
        organisation_id=organisation_id,
        actor_user_id=user_id,
        brand_kit_id=brand_kit_id,
        brand_kit_version_id=version.id,
        action="VERSION_ARCHIVED",
        resource_type=BrandAuditResourceType.VERSION,
        resource_id=version.id,
        details_json={"version_number": version.version_number},
    )
    db.add(audit)
    db.commit()
    db.refresh(version)
    return version


def set_active_version(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
) -> BrandKit:
    """Set the active published version for a Brand Kit.

    Enforces that the version belongs to the authenticated organisation,
    belongs to this exact Brand Kit, and is in PUBLISHED status.
    """
    kit = get_brand_kit_or_404(
        db,
        organisation_id=organisation_id,
        brand_kit_id=brand_kit_id,
        for_update=True,
    )

    version = db.execute(
        select(BrandKitVersion).where(BrandKitVersion.id == version_id)
    ).scalar_one_or_none()

    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Selected Brand Kit version not found.",
        )

    if version.organisation_id != organisation_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Selected Brand Kit version not found in this organisation.",
        )

    if version.brand_kit_id != brand_kit_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected version belongs to a different Brand Kit.",
        )

    if version.status != BrandKitVersionStatus.PUBLISHED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Only PUBLISHED versions can be set as active. "
                f"Selected version {version.version_number} is {version.status}."
            ),
        )

    kit.active_version_id = version.id
    kit.updated_at = utcnow()
    db.flush()

    audit = BrandAuditLog(
        id=uuid.uuid4(),
        organisation_id=organisation_id,
        actor_user_id=user_id,
        brand_kit_id=kit.id,
        brand_kit_version_id=version.id,
        action="ACTIVE_VERSION_SET",
        resource_type=BrandAuditResourceType.BRAND_KIT,
        resource_id=kit.id,
        details_json={
            "active_version_id": str(version.id),
            "version_number": version.version_number,
        },
    )
    db.add(audit)
    db.commit()
    db.refresh(kit)
    return kit
