"""Brand Guideline Document Ingestion and Management Service (Phase 6.1).

Primary Responsibilities:
- Multi-tenant and Brand-Kit-scoped authorization for guideline document lifecycle.
- Bounded 10MB streaming upload with extension/magic-byte validation.
- Threadpool offloaded text extraction (PDF, DOCX, TXT) and sentence-aware chunking.
- Immutability enforcement: mutations strictly restricted to DRAFT versions.
- Cleanup of physical files on failed database persistence (SEC-06).
- Canonical path containment and orphan file prevention on deletion (CR-03).
"""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.routes.compliance import get_extraction_semaphore
from app.models.brand import (
    BrandAuditLog,
    BrandAuditResourceType,
    BrandDocumentChunk,
    BrandGuidelineDocument,
    BrandKitVersion,
    BrandKitVersionStatus,
    DocumentParsingStatus,
    GuidelineDocumentCategory,
    utcnow,
)
from app.schemas import BrandDocumentChunkResponse, BrandGuidelineDocumentResponse
from app.services import brand_kit_service
from app.services import document_extraction_service as doc_service
from app.services.rag import chunking_service

# Allowed guideline document extensions (text-heavy policy documents)
ALLOWED_GUIDELINE_EXTENSIONS = {".pdf", ".docx", ".txt"}


def document_to_response(doc: BrandGuidelineDocument) -> BrandGuidelineDocumentResponse:
    """Serialize BrandGuidelineDocument ORM model into schema response."""
    return BrandGuidelineDocumentResponse(
        id=doc.id,
        brand_kit_version_id=doc.brand_kit_version_id,
        organisation_id=doc.organisation_id,
        title=doc.title,
        document_category=doc.document_category,
        original_filename=doc.original_filename,
        stored_filename=doc.stored_filename,
        file_size_bytes=doc.file_size_bytes,
        file_sha256=doc.file_sha256,
        page_count=doc.page_count,
        parsing_status=doc.parsing_status,
        parse_attempt_count=doc.parse_attempt_count,
        last_error_code=doc.last_error_code,
        last_error_message=doc.last_error_message,
        chunks_count=len(doc.chunks) if doc.chunks is not None else 0,
        created_at=doc.created_at,
        parsed_at=doc.parsed_at,
        embedded_at=doc.embedded_at,
        uploaded_by_user_id=doc.uploaded_by_user_id,
    )


def chunk_to_response(chunk: BrandDocumentChunk) -> BrandDocumentChunkResponse:
    """Serialize BrandDocumentChunk ORM model into schema response."""
    return BrandDocumentChunkResponse(
        id=chunk.id,
        document_id=chunk.document_id,
        brand_kit_version_id=chunk.brand_kit_version_id,
        organisation_id=chunk.organisation_id,
        chunk_index=chunk.chunk_index,
        page_number=chunk.page_number,
        section_heading=chunk.section_heading,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        content=chunk.content,
        content_sha256=chunk.content_sha256,
        token_count=chunk.token_count,
        created_at=chunk.created_at,
    )


def _validate_draft_version(version: BrandKitVersion) -> None:
    """Ensure the target version is in DRAFT status. Reject mutations to PUBLISHED/ARCHIVED versions."""
    if version.status != BrandKitVersionStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Brand Kit version is {version.status} and immutable. Create a draft version to modify guideline documents.",
        )


def _get_guideline_document_or_404(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    brand_kit_version_id: uuid.UUID,
    document_id: uuid.UUID,
    for_update: bool = False,
) -> BrandGuidelineDocument:
    """Retrieve BrandGuidelineDocument strictly scoped to version and organisation."""
    stmt = select(BrandGuidelineDocument).where(
        BrandGuidelineDocument.id == document_id,
        BrandGuidelineDocument.brand_kit_version_id == brand_kit_version_id,
        BrandGuidelineDocument.organisation_id == organisation_id,
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    doc = db.execute(stmt).scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guideline document not found in this version.",
        )
    return doc


async def upload_guideline_document(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    file: UploadFile,
    title: str | None = None,
    document_category: str = GuidelineDocumentCategory.STYLE_GUIDE,
) -> BrandGuidelineDocument:
    """Upload, extract, chunk, and persist a brand guideline document into a DRAFT BrandKitVersion."""
    # 1. Authoritative ownership & version status validation
    brand_kit_service.get_brand_kit_or_404(
        db, organisation_id=organisation_id, brand_kit_id=brand_kit_id
    )
    version = brand_kit_service.get_brand_kit_version_or_404(
        db,
        organisation_id=organisation_id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        for_update=True,
    )
    _validate_draft_version(version)

    # Validate document category against GuidelineDocumentCategory.ALL (CR-61-02)
    if document_category not in GuidelineDocumentCategory.ALL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid document category '{document_category}'. Allowed categories: {', '.join(GuidelineDocumentCategory.ALL)}.",
        )

    # 2. Extension pre-validation
    raw_filename = file.filename or "guideline_document"
    ext = os.path.splitext(raw_filename.lower())[1]
    if ext not in ALLOWED_GUIDELINE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported guideline format '{ext}'. Allowed extensions: {', '.join(sorted(ALLOWED_GUIDELINE_EXTENSIONS))}.",
        )

    # 3. Bounded chunked streaming read (SEC-02 10MB limit)
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        chunk = await file.read(doc_service.UPLOAD_CHUNK_SIZE_BYTES)
        if not chunk:
            break
        total_bytes += len(chunk)
        if total_bytes > doc_service.MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Guideline document exceeds maximum allowed size of {doc_service.MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB.",
            )
        chunks.append(chunk)

    if total_bytes == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded guideline document is empty (0 bytes).",
        )

    content = b"".join(chunks)

    # 4. Offload extraction to worker threadpool with concurrency semaphore (SEC-01, SEC-04)
    semaphore = get_extraction_semaphore()
    try:
        async with semaphore:
            extraction = await run_in_threadpool(doc_service.extract_document_text, raw_filename, content)
    except doc_service.UnsupportedFileError as ufe:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(ufe)) from ufe
    except doc_service.ExtractionError as ee:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(ee)) from ee

    if not extraction.text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Extracted document contains no readable text.",
        )

    # 5. Store file safely in organisation storage directory (CR-03 canonical path containment)
    rel_path, safe_name = doc_service.store_uploaded_file(
        organisation_id=organisation_id,
        filename=raw_filename,
        content=content,
    )
    dest_file_path = (doc_service.LOCAL_UPLOAD_ROOT / rel_path).resolve()

    try:
        # 6. Create BrandGuidelineDocument record
        doc_id = uuid.uuid4()
        doc_title = (title or safe_name).strip()[:200]
        file_sha = hashlib.sha256(content).hexdigest()
        detected_mime = extraction.metadata.get("mime_type") or "application/octet-stream"

        doc = BrandGuidelineDocument(
            id=doc_id,
            brand_kit_version_id=version_id,
            organisation_id=organisation_id,
            title=doc_title,
            document_category=document_category,
            original_filename=raw_filename[:255],
            stored_filename=safe_name,
            storage_backend="LOCAL",
            storage_path=rel_path,
            mime_type=detected_mime,
            file_size_bytes=total_bytes,
            file_sha256=file_sha,
            page_count=extraction.page_count,
            parsing_status=DocumentParsingStatus.PARSED,
            parse_attempt_count=1,
            raw_text_content=extraction.text,
            parsed_at=utcnow(),
            uploaded_by_user_id=user_id,
        )
        db.add(doc)

        # 7. Generate sentence-aware chunks
        chunks_orm = chunking_service.chunk_document_text(
            text=extraction.text,
            document_id=doc_id,
            brand_kit_version_id=version_id,
            organisation_id=organisation_id,
            page_metadata=extraction.pages,
        )
        for c in chunks_orm:
            db.add(c)

        # 8. Record audit log entry
        audit = BrandAuditLog(
            id=uuid.uuid4(),
            organisation_id=organisation_id,
            actor_user_id=user_id,
            brand_kit_id=brand_kit_id,
            action="GUIDELINE_DOCUMENT_UPLOADED",
            resource_type=BrandAuditResourceType.BRAND_KIT,
            resource_id=doc_id,
            details_json={
                "title": doc_title,
                "document_category": document_category,
                "file_sha256": file_sha,
                "chunks_count": len(chunks_orm),
                "page_count": extraction.page_count,
            },
        )
        db.add(audit)
        db.commit()
        db.refresh(doc)
        return doc
    except Exception:
        # SEC-06: Clean up stored file if database flush or commit fails
        db.rollback()
        try:
            if dest_file_path.is_file():
                dest_file_path.unlink()
        except OSError:
            pass
        raise


def list_guideline_documents(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
) -> list[BrandGuidelineDocument]:
    """List all guideline documents for a version."""
    brand_kit_service.get_brand_kit_or_404(
        db, organisation_id=organisation_id, brand_kit_id=brand_kit_id
    )
    brand_kit_service.get_brand_kit_version_or_404(
        db, organisation_id=organisation_id, brand_kit_id=brand_kit_id, version_id=version_id
    )
    stmt = (
        select(BrandGuidelineDocument)
        .where(
            BrandGuidelineDocument.brand_kit_version_id == version_id,
            BrandGuidelineDocument.organisation_id == organisation_id,
        )
        .order_by(BrandGuidelineDocument.created_at.desc())
    )
    return list(db.execute(stmt).scalars().all())


def get_guideline_document(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    document_id: uuid.UUID,
) -> BrandGuidelineDocument:
    """Get single guideline document with version & organisation validation."""
    brand_kit_service.get_brand_kit_or_404(
        db, organisation_id=organisation_id, brand_kit_id=brand_kit_id
    )
    brand_kit_service.get_brand_kit_version_or_404(
        db, organisation_id=organisation_id, brand_kit_id=brand_kit_id, version_id=version_id
    )
    return _get_guideline_document_or_404(
        db,
        organisation_id=organisation_id,
        brand_kit_version_id=version_id,
        document_id=document_id,
    )


def delete_guideline_document(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    document_id: uuid.UUID,
) -> None:
    """Delete a guideline document and its chunks from a DRAFT version.

    Only unlinks physical file if no other document references the same storage_path.
    """
    brand_kit_service.get_brand_kit_or_404(
        db, organisation_id=organisation_id, brand_kit_id=brand_kit_id
    )
    version = brand_kit_service.get_brand_kit_version_or_404(
        db,
        organisation_id=organisation_id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        for_update=True,
    )
    _validate_draft_version(version)

    doc = _get_guideline_document_or_404(
        db,
        organisation_id=organisation_id,
        brand_kit_version_id=version_id,
        document_id=document_id,
        for_update=True,
    )

    storage_path = doc.storage_path
    doc_title = doc.title

    # Delete document record (foreign keys cascade delete chunks)
    db.delete(doc)
    db.flush()

    # Check if any other document still references the same storage_path
    other_refs = db.scalar(
        select(func.count(BrandGuidelineDocument.id)).where(
            BrandGuidelineDocument.id != document_id,
            BrandGuidelineDocument.storage_path == storage_path,
        )
    )

    audit = BrandAuditLog(
        id=uuid.uuid4(),
        organisation_id=organisation_id,
        actor_user_id=user_id,
        brand_kit_id=brand_kit_id,
        action="GUIDELINE_DOCUMENT_DELETED",
        resource_type=BrandAuditResourceType.BRAND_KIT,
        resource_id=document_id,
        details_json={
            "deleted_document_title": doc_title,
            "storage_path": storage_path,
            "remaining_file_references": other_refs,
        },
    )
    db.add(audit)
    db.commit()

    # Only unlink physical file if no other version/document references it
    if other_refs == 0:
        file_dest = (doc_service.LOCAL_UPLOAD_ROOT / storage_path).resolve()
        if (
            file_dest.is_file()
            and file_dest.is_relative_to(doc_service.LOCAL_UPLOAD_ROOT.resolve())
        ):
            try:
                file_dest.unlink()
            except OSError:
                pass


async def reparse_guideline_document(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    document_id: uuid.UUID,
) -> BrandGuidelineDocument:
    """Reparse and rechunk an existing guideline document on a DRAFT version."""
    brand_kit_service.get_brand_kit_or_404(
        db, organisation_id=organisation_id, brand_kit_id=brand_kit_id
    )
    version = brand_kit_service.get_brand_kit_version_or_404(
        db,
        organisation_id=organisation_id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        for_update=True,
    )
    _validate_draft_version(version)

    doc = _get_guideline_document_or_404(
        db,
        organisation_id=organisation_id,
        brand_kit_version_id=version_id,
        document_id=document_id,
        for_update=True,
    )

    file_path = (doc_service.LOCAL_UPLOAD_ROOT / doc.storage_path).resolve()
    if not file_path.is_file() or not file_path.is_relative_to(doc_service.LOCAL_UPLOAD_ROOT.resolve()):
        doc.parsing_status = DocumentParsingStatus.FAILED
        doc.last_error_code = "FILE_NOT_FOUND"
        doc.last_error_message = "Stored document binary is missing from filesystem."
        doc.parse_attempt_count += 1
        db.commit()
        db.refresh(doc)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stored guideline document binary is missing from filesystem storage.",
        )

    try:
        content = file_path.read_bytes()
    except OSError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read stored guideline binary: {e}",
        )

    # Offload extraction to worker threadpool with concurrency semaphore
    semaphore = get_extraction_semaphore()
    doc.parse_attempt_count += 1
    doc.parsing_status = DocumentParsingStatus.PROCESSING

    try:
        async with semaphore:
            extraction = await run_in_threadpool(doc_service.extract_document_text, doc.original_filename, content)

        # Clear existing chunks
        for c in list(doc.chunks):
            db.delete(c)
        db.flush()

        # Generate new chunks
        new_chunks = chunking_service.chunk_document_text(
            text=extraction.text,
            document_id=doc.id,
            brand_kit_version_id=version_id,
            organisation_id=organisation_id,
            page_metadata=extraction.pages,
        )
        for nc in new_chunks:
            db.add(nc)

        doc.raw_text_content = extraction.text
        doc.page_count = extraction.page_count
        doc.parsing_status = DocumentParsingStatus.PARSED
        doc.parsed_at = utcnow()
        doc.last_error_code = None
        doc.last_error_message = None

        audit = BrandAuditLog(
            id=uuid.uuid4(),
            organisation_id=organisation_id,
            actor_user_id=user_id,
            brand_kit_id=brand_kit_id,
            action="GUIDELINE_DOCUMENT_REPARSED",
            resource_type=BrandAuditResourceType.BRAND_KIT,
            resource_id=doc.id,
            details_json={
                "chunks_count": len(new_chunks),
                "parse_attempt_count": doc.parse_attempt_count,
            },
        )
        db.add(audit)
        db.commit()
        db.refresh(doc)
        return doc
    except Exception as exc:
        # CR-61-01: Rollback failed transaction to preserve existing chunks and avoid committing partial deletion
        db.rollback()
        try:
            failed_doc = _get_guideline_document_or_404(
                db,
                organisation_id=organisation_id,
                brand_kit_version_id=version_id,
                document_id=document_id,
                for_update=True,
            )
            failed_doc.parsing_status = DocumentParsingStatus.FAILED
            failed_doc.last_error_code = "EXTRACTION_FAILED"
            failed_doc.last_error_message = str(exc)[:500]
            failed_doc.parse_attempt_count += 1
            db.commit()
            db.refresh(failed_doc)
        except Exception:
            db.rollback()

        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Reparsing failed: {exc}",
        ) from exc


def list_document_chunks(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    document_id: uuid.UUID,
) -> list[BrandDocumentChunk]:
    """Retrieve all chunks belonging to a guideline document, ordered by chunk_index."""
    get_guideline_document(
        db,
        organisation_id=organisation_id,
        brand_kit_id=brand_kit_id,
        version_id=version_id,
        document_id=document_id,
    )
    stmt = (
        select(BrandDocumentChunk)
        .where(
            BrandDocumentChunk.document_id == document_id,
            BrandDocumentChunk.brand_kit_version_id == version_id,
            BrandDocumentChunk.organisation_id == organisation_id,
        )
        .order_by(BrandDocumentChunk.chunk_index.asc())
    )
    return list(db.execute(stmt).scalars().all())
