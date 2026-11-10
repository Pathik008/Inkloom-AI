"""Brand Kit management and version lifecycle API routes.

Provides REST endpoints for Brand Kit container CRUD, sequential version
creation, pre-publish validation, atomic publishing, archiving, and active version selection.
Strict tenant isolation and granular RBAC are enforced on all routes.
"""
import uuid
from typing import List

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import (
    TenantContext,
    require_permission,
)
from app.database import get_db
from app.models import (
    BrandIdentity,
    BrandKit,
    BrandKitVersion,
    BrandKitVersionStatus,
    GuidelineDocumentCategory,
    PermissionCode,
)
from app.schemas import (
    BrandDocumentChunkResponse,
    BrandGuidelineDocumentResponse,
    BrandIdentityResponse,
    BrandKitCreateRequest,
    BrandKitDetailResponse,
    BrandKitSummaryResponse,
    BrandKitUpdateRequest,
    BrandKitVersionCreateRequest,
    BrandKitVersionDetailResponse,
    BrandKitVersionSummaryResponse,
    BrandKitVersionUpdateRequest,
    RetrievedChunkResponse,
    SemanticRetrievalRequest,
    SemanticRetrievalResponse,
    SetActiveVersionRequest,
)
from app.services import brand_kit_service, guideline_document_service
from app.services.rag import embed_guideline_document, retrieve_candidate_chunks

router = APIRouter()


def _build_identity_response(identity: BrandIdentity | None) -> BrandIdentityResponse | None:
    if identity is None:
        return None
    return BrandIdentityResponse.model_validate(identity)


def _build_version_summary(ver: BrandKitVersion) -> BrandKitVersionSummaryResponse:
    return BrandKitVersionSummaryResponse.model_validate(ver)


def _build_version_detail(ver: BrandKitVersion) -> BrandKitVersionDetailResponse:
    return BrandKitVersionDetailResponse(
        id=ver.id,
        brand_kit_id=ver.brand_kit_id,
        organisation_id=ver.organisation_id,
        version_number=ver.version_number,
        status=ver.status,
        changelog=ver.changelog,
        cloned_from_version_id=ver.cloned_from_version_id,
        created_by_user_id=ver.created_by_user_id,
        published_by_user_id=ver.published_by_user_id,
        published_at=ver.published_at,
        archived_by_user_id=ver.archived_by_user_id,
        archived_at=ver.archived_at,
        created_at=ver.created_at,
        updated_at=ver.updated_at,
        identity=_build_identity_response(ver.identity),
        facts_count=len(ver.facts) if ver.facts is not None else 0,
        rules_count=len(ver.rules) if ver.rules is not None else 0,
        assets_count=len(ver.assets) if ver.assets is not None else 0,
        documents_count=len(ver.documents) if ver.documents is not None else 0,
    )


def _build_kit_summary(kit: BrandKit) -> BrandKitSummaryResponse:
    active_ver = None
    draft_ver = None
    for v in kit.versions or []:
        if kit.active_version_id and v.id == kit.active_version_id:
            active_ver = _build_version_summary(v)
        elif active_ver is None and v.status == BrandKitVersionStatus.PUBLISHED:
            active_ver = _build_version_summary(v)
        if v.status == BrandKitVersionStatus.DRAFT:
            draft_ver = _build_version_summary(v)

    return BrandKitSummaryResponse(
        id=kit.id,
        organisation_id=kit.organisation_id,
        name=kit.name,
        slug=kit.slug,
        description=kit.description,
        industry=kit.industry,
        active_version_id=kit.active_version_id,
        is_archived=kit.is_archived,
        created_by_user_id=kit.created_by_user_id,
        created_at=kit.created_at,
        updated_at=kit.updated_at,
        active_version=active_ver,
        draft_version=draft_ver,
    )


def _build_kit_detail(kit: BrandKit) -> BrandKitDetailResponse:
    summary = _build_kit_summary(kit)
    sorted_versions = sorted(
        kit.versions or [],
        key=lambda v: v.version_number,
        reverse=True,
    )
    return BrandKitDetailResponse(
        **summary.model_dump(),
        versions=[_build_version_summary(v) for v in sorted_versions],
    )


@router.get(
    "",
    response_model=List[BrandKitSummaryResponse],
    summary="List Brand Kits",
    description="List all Brand Kits for the organisation (requires brand:read).",
)
def list_brand_kits(
    include_archived: bool = Query(default=False, description="Include soft-archived Brand Kits"),
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_READ)),
    db: Session = Depends(get_db),
) -> List[BrandKitSummaryResponse]:
    kits = brand_kit_service.list_brand_kits(
        db,
        organisation_id=context.organisation.id,
        include_archived=include_archived,
    )
    return [_build_kit_summary(k) for k in kits]


@router.post(
    "",
    response_model=BrandKitDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Brand Kit",
    description="Create a new Brand Kit container with initial DRAFT Version 1 (requires brand:manage).",
)
def create_brand_kit(
    payload: BrandKitCreateRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_MANAGE)),
    db: Session = Depends(get_db),
) -> BrandKitDetailResponse:
    kit = brand_kit_service.create_brand_kit(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        payload=payload,
    )
    return _build_kit_detail(kit)


@router.get(
    "/{brand_kit_id}",
    response_model=BrandKitDetailResponse,
    summary="Get Brand Kit details",
    description="Retrieve Brand Kit metadata and complete version history (requires brand:read).",
)
def get_brand_kit(
    brand_kit_id: uuid.UUID,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_READ)),
    db: Session = Depends(get_db),
) -> BrandKitDetailResponse:
    kit = brand_kit_service.get_brand_kit_or_404(
        db,
        organisation_id=context.organisation.id,
        brand_kit_id=brand_kit_id,
    )
    return _build_kit_detail(kit)


@router.patch(
    "/{brand_kit_id}",
    response_model=BrandKitDetailResponse,
    summary="Update Brand Kit",
    description="Update Brand Kit container metadata (requires brand:manage).",
)
def update_brand_kit(
    brand_kit_id: uuid.UUID,
    payload: BrandKitUpdateRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_MANAGE)),
    db: Session = Depends(get_db),
) -> BrandKitDetailResponse:
    kit = brand_kit_service.update_brand_kit(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        brand_kit_id=brand_kit_id,
        payload=payload,
    )
    return _build_kit_detail(kit)


@router.post(
    "/{brand_kit_id}/versions",
    response_model=BrandKitVersionDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Draft Version",
    description="Clone a new sequential DRAFT version from active or specified version (requires brand:manage).",
)
def create_version(
    brand_kit_id: uuid.UUID,
    payload: BrandKitVersionCreateRequest | None = None,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_MANAGE)),
    db: Session = Depends(get_db),
) -> BrandKitVersionDetailResponse:
    version = brand_kit_service.create_draft_version(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        brand_kit_id=brand_kit_id,
        payload=payload,
    )
    return _build_version_detail(version)


@router.get(
    "/{brand_kit_id}/versions/{version_id}",
    response_model=BrandKitVersionDetailResponse,
    summary="Get Version Details",
    description="Retrieve a Brand Kit version and its 1:1 BrandIdentity (requires brand:read).",
)
def get_version(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_READ)),
    db: Session = Depends(get_db),
) -> BrandKitVersionDetailResponse:
    version = brand_kit_service.get_brand_kit_version_or_404(
        db,
        organisation_id=context.organisation.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
    )
    return _build_version_detail(version)


@router.patch(
    "/{brand_kit_id}/versions/{version_id}",
    response_model=BrandKitVersionDetailResponse,
    summary="Update Draft Version",
    description="Update changelog or BrandIdentity on a DRAFT version (requires brand:manage; returns 409 if not DRAFT).",
)
def update_draft_version(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: BrandKitVersionUpdateRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_MANAGE)),
    db: Session = Depends(get_db),
) -> BrandKitVersionDetailResponse:
    version = brand_kit_service.update_draft_version(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        payload=payload,
    )
    return _build_version_detail(version)


@router.post(
    "/{brand_kit_id}/versions/{version_id}/publish",
    response_model=BrandKitVersionDetailResponse,
    summary="Publish Version",
    description="Validate quality gates and atomically publish a DRAFT version (requires brand:manage).",
)
def publish_version(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_MANAGE)),
    db: Session = Depends(get_db),
) -> BrandKitVersionDetailResponse:
    version = brand_kit_service.publish_version(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
    )
    return _build_version_detail(version)


@router.post(
    "/{brand_kit_id}/versions/{version_id}/archive",
    response_model=BrandKitVersionDetailResponse,
    summary="Archive Version",
    description="Atomically archive a PUBLISHED version and clear active_version_id if active (requires brand:manage).",
)
def archive_version(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_MANAGE)),
    db: Session = Depends(get_db),
) -> BrandKitVersionDetailResponse:
    version = brand_kit_service.archive_version(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
    )
    return _build_version_detail(version)


@router.post(
    "/{brand_kit_id}/active-version",
    response_model=BrandKitDetailResponse,
    summary="Set Active Version (Body)",
    description="Set the active published version for a Brand Kit (requires brand:manage).",
)
def set_active_version_body(
    brand_kit_id: uuid.UUID,
    payload: SetActiveVersionRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_MANAGE)),
    db: Session = Depends(get_db),
) -> BrandKitDetailResponse:
    kit = brand_kit_service.set_active_version(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        brand_kit_id=brand_kit_id,
        version_id=payload.version_id,
    )
    return _build_kit_detail(kit)


@router.post(
    "/{brand_kit_id}/versions/{version_id}/set-active",
    response_model=BrandKitDetailResponse,
    summary="Set Active Version (Path)",
    description="Set the active published version for a Brand Kit by version path (requires brand:manage).",
)
def set_active_version_path(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_MANAGE)),
    db: Session = Depends(get_db),
) -> BrandKitDetailResponse:
    kit = brand_kit_service.set_active_version(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
    )
    return _build_kit_detail(kit)


# ==============================================================================
# Brand Guideline Document Management Endpoints (Phase 6.1)
# ==============================================================================


@router.post(
    "/{brand_kit_id}/versions/{version_id}/documents",
    response_model=BrandGuidelineDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload Guideline Document",
    description="Upload, extract text, chunk, and attach a guideline document to a DRAFT version (requires brand:manage).",
)
async def upload_guideline_document(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    file: UploadFile = File(..., description="Guideline document (PDF, DOCX, TXT) max 10MB"),
    title: str | None = Form(default=None, description="Display title for guideline document"),
    document_category: str = Form(
        default=GuidelineDocumentCategory.STYLE_GUIDE,
        description="Category: STYLE_GUIDE, PRODUCT_CATALOG, LEGAL_POLICY, TONE_PLAYBOOK, BRAND_BOOK",
    ),
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_MANAGE)),
    db: Session = Depends(get_db),
) -> BrandGuidelineDocumentResponse:
    doc = await guideline_document_service.upload_guideline_document(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        file=file,
        title=title,
        document_category=document_category,
    )
    return guideline_document_service.document_to_response(doc)


@router.get(
    "/{brand_kit_id}/versions/{version_id}/documents",
    response_model=List[BrandGuidelineDocumentResponse],
    summary="List Guideline Documents",
    description="List all guideline documents attached to a Brand Kit version (requires brand:read).",
)
def list_guideline_documents(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_READ)),
    db: Session = Depends(get_db),
) -> List[BrandGuidelineDocumentResponse]:
    docs = guideline_document_service.list_guideline_documents(
        db,
        organisation_id=context.organisation.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
    )
    return [guideline_document_service.document_to_response(d) for d in docs]


@router.get(
    "/{brand_kit_id}/versions/{version_id}/documents/{document_id}",
    response_model=BrandGuidelineDocumentResponse,
    summary="Get Guideline Document",
    description="Get metadata and processing telemetry for a single guideline document (requires brand:read).",
)
def get_guideline_document(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    document_id: uuid.UUID,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_READ)),
    db: Session = Depends(get_db),
) -> BrandGuidelineDocumentResponse:
    doc = guideline_document_service.get_guideline_document(
        db,
        organisation_id=context.organisation.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        document_id=document_id,
    )
    return guideline_document_service.document_to_response(doc)


@router.delete(
    "/{brand_kit_id}/versions/{version_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Guideline Document",
    description="Delete a guideline document and its chunks from a DRAFT version (requires brand:manage).",
)
def delete_guideline_document(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    document_id: uuid.UUID,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_MANAGE)),
    db: Session = Depends(get_db),
):
    guideline_document_service.delete_guideline_document(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        document_id=document_id,
    )


@router.post(
    "/{brand_kit_id}/versions/{version_id}/documents/{document_id}/reparse",
    response_model=BrandGuidelineDocumentResponse,
    summary="Reparse Guideline Document",
    description="Reparse and re-chunk an existing guideline document on a DRAFT version (requires brand:manage).",
)
async def reparse_guideline_document(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    document_id: uuid.UUID,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_MANAGE)),
    db: Session = Depends(get_db),
) -> BrandGuidelineDocumentResponse:
    doc = await guideline_document_service.reparse_guideline_document(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        document_id=document_id,
    )
    return guideline_document_service.document_to_response(doc)


@router.get(
    "/{brand_kit_id}/versions/{version_id}/documents/{document_id}/chunks",
    response_model=List[BrandDocumentChunkResponse],
    summary="List Document Chunks",
    description="List all sentence-aware chunks belonging to a guideline document (requires brand:read).",
)
def list_document_chunks(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    document_id: uuid.UUID,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_READ)),
    db: Session = Depends(get_db),
) -> List[BrandDocumentChunkResponse]:
    chunks = guideline_document_service.list_document_chunks(
        db,
        organisation_id=context.organisation.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        document_id=document_id,
    )
    return [guideline_document_service.chunk_to_response(c) for c in chunks]


# ==============================================================================
# Phase 6.2 Embedding & Tenant-Isolated Retrieval Endpoints
# ==============================================================================


@router.post(
    "/{brand_kit_id}/versions/{version_id}/documents/{document_id}/embed",
    response_model=BrandGuidelineDocumentResponse,
    summary="Generate Embeddings for Guideline Document",
    description="Generate and persist vector embeddings for existing parsed chunks on a DRAFT version (requires brand:manage).",
)
async def trigger_document_embeddings(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    document_id: uuid.UUID,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_MANAGE)),
    db: Session = Depends(get_db),
) -> BrandGuidelineDocumentResponse:
    doc = await embed_guideline_document(
        db,
        organisation_id=context.organisation.id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        document_id=document_id,
    )
    return guideline_document_service.document_to_response(doc)


@router.post(
    "/{brand_kit_id}/versions/{version_id}/retrieve",
    response_model=SemanticRetrievalResponse,
    summary="Semantic Vector Retrieval across Guideline Chunks",
    description="Query semantically relevant guideline chunks strictly scoped to organisation and Brand Kit version (requires brand:read).",
)
async def semantic_retrieve_chunks(
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: SemanticRetrievalRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.BRAND_READ)),
    db: Session = Depends(get_db),
) -> SemanticRetrievalResponse:
    # 1. Authoritative ownership verification
    brand_kit_service.get_brand_kit_or_404(
        db, organisation_id=context.organisation.id, brand_kit_id=brand_kit_id
    )
    brand_kit_service.get_brand_kit_version_or_404(
        db, organisation_id=context.organisation.id, brand_kit_id=brand_kit_id, version_id=version_id
    )

    # 2. Retrieve candidate chunks with strict composite scoping
    retrieved = await retrieve_candidate_chunks(
        db,
        organisation_id=context.organisation.id,
        brand_kit_version_id=version_id,
        query_text=payload.query_text,
        top_k=payload.top_k,
        similarity_threshold=payload.similarity_threshold,
    )

    chunk_responses = [
        RetrievedChunkResponse(
            chunk_id=r.chunk_id,
            document_id=r.document_id,
            document_title=r.document_title,
            chunk_index=r.chunk_index,
            page_number=r.page_number,
            section_heading=r.section_heading,
            char_start=r.char_start,
            char_end=r.char_end,
            content=r.content,
            content_sha256=r.content_sha256,
            token_count=r.token_count,
            similarity_score=r.similarity_score,
            is_mock=r.is_mock,
        )
        for r in retrieved
    ]

    return SemanticRetrievalResponse(
        query=payload.query_text,
        chunks_count=len(chunk_responses),
        chunks=chunk_responses,
    )
