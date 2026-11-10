"""Content submission, compliance analysis, and human approval routes."""
import asyncio
import uuid
from typing import List

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import TenantContext, require_permission
from app.database import get_db
from app.models import PermissionCode
from app.schemas import (
    AddCommentRequest,
    ApplyCorrectionsRequest,
    ApprovalDecisionRequest,
    AssignReviewerRequest,
    ComplianceMetricsResponse,
    ContentRevisionRequest,
    ContentSubmissionCreateRequest,
    ContentSubmissionResponse,
    ContentSubmissionSummaryResponse,
    DocumentExtractionResponse,
    ReviewActionResponse,
    ReviewerUserResponse,
    SubmitForApprovalRequest,
)
from app.services import brand_kit_service
from app.services import compliance_service
from app.services import document_extraction_service as doc_service

router = APIRouter()
reviewers_router = APIRouter()
metrics_router = APIRouter()

# Concurrency throttle: maximum 5 concurrent CPU-bound document extraction jobs (SEC-01)
MAX_CONCURRENT_EXTRACTIONS = 5
_extraction_semaphore: asyncio.Semaphore | None = None
_semaphore_loop = None


def get_extraction_semaphore() -> asyncio.Semaphore:
    """Return a shared singleton semaphore bound to the running event loop (SEC-01)."""
    global _extraction_semaphore, _semaphore_loop
    current_loop = asyncio.get_running_loop()
    if _extraction_semaphore is None or _semaphore_loop != current_loop:
        _extraction_semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXTRACTIONS)
        _semaphore_loop = current_loop
    return _extraction_semaphore


@router.post(
    "",
    response_model=ContentSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit marketing text and run compliance analysis",
)
@router.post(
    "/analyze",
    response_model=ContentSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit marketing text and run compliance analysis (hybrid or deterministic)",
)
def submit_content(
    payload: ContentSubmissionCreateRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_CREATE)),
    db: Session = Depends(get_db),
):
    submission = compliance_service.submit_content(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        brand_kit_id=payload.brand_kit_id,
        title=payload.title,
        content_text=payload.content_text,
        mode=payload.mode,
        include_experimental_score=payload.include_experimental_score,
    )
    return compliance_service.submission_to_dict(submission)


@router.post(
    "/upload",
    response_model=DocumentExtractionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload PDF, DOCX, TXT or image, extract text, and optionally run compliance analysis",
)
async def upload_and_process_document(
    file: UploadFile = File(..., description="Uploaded document (PDF, DOCX, TXT, PNG, JPEG)"),
    brand_kit_id: uuid.UUID = Form(..., description="Target Brand Kit ID"),
    title: str | None = Form(default=None, description="Optional custom title for the submission"),
    auto_submit: bool = Form(default=True, description="Whether to automatically submit extracted text for compliance review"),
    mode: str = Form(default="deterministic", description="Compliance review mode: deterministic or hybrid"),
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_CREATE)),
    db: Session = Depends(get_db),
):
    """Secure document ingestion & text extraction endpoint (Phase 5.3 / 5.4)."""
    # 0. Validate Brand Kit tenant ownership & active status unconditionally (SEC-08)
    brand_kit = brand_kit_service.get_brand_kit_or_404(
        db,
        organisation_id=context.organisation.id,
        brand_kit_id=brand_kit_id,
    )
    if brand_kit.is_archived:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Target Brand Kit is archived.",
        )

    # 1. Bounded chunked file reading (SEC-02)
    # Note: Application-level chunking bounds memory inside the route handler,
    # though ASGI server/reverse proxy buffers may hold request body.
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
                detail=f"File exceeds maximum allowed size of {doc_service.MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB.",
            )
        chunks.append(chunk)

    if total_bytes == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty (0 bytes).",
        )

    content = b"".join(chunks)

    # 2. Extract text and validate format offloaded to worker thread with bounded concurrency (SEC-01, SEC-04)
    filename = file.filename or "uploaded_document"
    try:
        semaphore = get_extraction_semaphore()
        async with semaphore:
            extraction = await run_in_threadpool(doc_service.extract_document_text, filename, content)
    except doc_service.UnsupportedFileError as ufe:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(ufe)) from ufe
    except doc_service.ExtractionError as ee:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(ee)) from ee

    # 3. Store raw document safely in organisation storage
    rel_path, safe_name = doc_service.store_uploaded_file(
        organisation_id=context.organisation.id,
        filename=filename,
        content=content,
    )
    dest_file_path = doc_service.LOCAL_UPLOAD_ROOT / rel_path

    try:
        # 4. If auto_submit is enabled and extracted text exists, create a ContentSubmission
        submission_dict = None
        if auto_submit and extraction.text.strip():
            submission_title = (title or safe_name).strip()[:200]
            submission = compliance_service.submit_content(
                db,
                organisation_id=context.organisation.id,
                user_id=context.user.id,
                brand_kit_id=brand_kit_id,
                title=submission_title,
                content_text=extraction.text,
                mode=mode,
            )
            submission_dict = compliance_service.submission_to_dict(submission)

        return DocumentExtractionResponse(
            filename=safe_name,
            format=extraction.format,
            method=extraction.method,
            page_count=extraction.page_count,
            char_count=extraction.char_count,
            extracted_text=extraction.text,
            metadata={**extraction.metadata, "stored_path": rel_path},
            ocr_fallback_triggered=extraction.ocr_fallback_triggered,
            submission=submission_dict,
        )
    except Exception:
        # SEC-06: Clean up orphaned upload file if subsequent processing or persistence fails
        try:
            if dest_file_path.is_file():
                dest_file_path.unlink()
        except OSError:
            pass
        raise


@router.get("", response_model=List[ContentSubmissionSummaryResponse], summary="List content submissions")
def list_submissions(
    brand_kit_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None, description="Filter by status, e.g. PENDING_REVIEW, APPROVED, REJECTED"),
    limit: int = Query(default=100, ge=1, le=200),
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_REVIEW)),
    db: Session = Depends(get_db),
):
    rows = compliance_service.list_submissions(
        db, organisation_id=context.organisation.id, brand_kit_id=brand_kit_id, status_filter=status, limit=limit
    )
    out = []
    for s in rows:
        latest = s.analyses[-1] if s.analyses else None
        out.append(
            ContentSubmissionSummaryResponse(
                id=s.id,
                brand_kit_id=s.brand_kit_id,
                brand_kit_version_id=s.brand_kit_version_id,
                parent_submission_id=s.parent_submission_id,
                revision_number=s.revision_number,
                title=s.title,
                score=latest.score if latest else None,
                result=latest.result if latest else None,
                status=s.status,
                submitted_by_user_id=s.submitted_by_user_id,
                submitted_by_name=s.submitter.full_name if s.submitter else None,
                assigned_reviewer_id=s.assigned_reviewer_id,
                assigned_reviewer_name=s.assigned_reviewer.full_name if s.assigned_reviewer else None,
                reviewed_by_name=s.reviewed_by.full_name if s.reviewed_by else None,
                reviewed_at=s.reviewed_at,
                created_at=s.created_at,
            )
        )
    return out


@metrics_router.get(
    "",
    response_model=ComplianceMetricsResponse,
    summary="Get aggregated compliance submission metrics for organisation",
)
@router.get(
    "/metrics",
    response_model=ComplianceMetricsResponse,
    summary="Get aggregated compliance submission metrics for organisation",
)
def get_compliance_metrics(
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_REVIEW)),
    db: Session = Depends(get_db),
):
    """Accurate organisation-scoped submission counts using database SQL aggregation (SEC-07)."""
    return compliance_service.get_compliance_metrics(db, organisation_id=context.organisation.id)


@reviewers_router.get("", response_model=List[ReviewerUserResponse], summary="List eligible reviewers for this organisation")
@router.get("/reviewers", response_model=List[ReviewerUserResponse], summary="List eligible reviewers for this organisation")
def list_reviewers(
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_REVIEW)),
    db: Session = Depends(get_db),
):
    return compliance_service.list_eligible_reviewers(db, organisation_id=context.organisation.id)


@router.get("/{submission_id}", response_model=ContentSubmissionResponse, summary="Get submission, findings and comparison")
def get_submission(
    submission_id: uuid.UUID,
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_REVIEW)),
    db: Session = Depends(get_db),
):
    submission = compliance_service.get_submission_or_404(
        db, organisation_id=context.organisation.id, submission_id=submission_id
    )
    lineage = compliance_service.get_submission_lineage(
        db, organisation_id=context.organisation.id, submission=submission
    )
    return compliance_service.submission_to_dict(
        submission,
        comparison=compliance_service.build_comparison(db, submission),
        all_revisions=lineage,
    )


@router.post(
    "/{submission_id}/revisions",
    response_model=ContentSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save edited content as a new revision and re-run analysis",
)
def revise_content(
    submission_id: uuid.UUID,
    payload: ContentRevisionRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_CREATE)),
    db: Session = Depends(get_db),
):
    revision = compliance_service.revise_content(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        submission_id=submission_id,
        content_text=payload.content_text,
        title=payload.title,
    )
    lineage = compliance_service.get_submission_lineage(
        db, organisation_id=context.organisation.id, submission=revision
    )
    return compliance_service.submission_to_dict(
        revision,
        comparison=compliance_service.build_comparison(db, revision),
        all_revisions=lineage,
    )


@router.post(
    "/{submission_id}/apply-corrections",
    response_model=ContentSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Apply suggested corrections as a new revision and re-run analysis",
)
def apply_corrections(
    submission_id: uuid.UUID,
    payload: ApplyCorrectionsRequest | None = None,
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_CREATE)),
    db: Session = Depends(get_db),
):
    revision, report = compliance_service.apply_suggested_corrections(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        submission_id=submission_id,
        finding_ids=payload.finding_ids if payload else None,
    )
    lineage = compliance_service.get_submission_lineage(
        db, organisation_id=context.organisation.id, submission=revision
    )
    return compliance_service.submission_to_dict(
        revision,
        comparison=compliance_service.build_comparison(db, revision),
        correction_report={
            "applied_finding_ids": report["applied_finding_ids"],
            "skipped": report["skipped"],
        },
        all_revisions=lineage,
    )


@router.post(
    "/{submission_id}/submit-for-approval",
    response_model=ContentSubmissionResponse,
    summary="Submit marketing content for human review and approval",
)
def submit_for_approval(
    submission_id: uuid.UUID,
    payload: SubmitForApprovalRequest | None = None,
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_CREATE)),
    db: Session = Depends(get_db),
):
    submission = compliance_service.submit_for_approval(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        submission_id=submission_id,
        assigned_reviewer_id=payload.assigned_reviewer_id if payload else None,
        comments=payload.comments if payload else None,
    )
    lineage = compliance_service.get_submission_lineage(
        db, organisation_id=context.organisation.id, submission=submission
    )
    return compliance_service.submission_to_dict(
        submission,
        comparison=compliance_service.build_comparison(db, submission),
        all_revisions=lineage,
    )


@router.post(
    "/{submission_id}/assign-reviewer",
    response_model=ContentSubmissionResponse,
    summary="Assign a reviewer to a content submission",
)
def assign_reviewer(
    submission_id: uuid.UUID,
    payload: AssignReviewerRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.APPROVAL_DECIDE)),
    db: Session = Depends(get_db),
):
    submission = compliance_service.assign_reviewer(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        submission_id=submission_id,
        reviewer_id=payload.reviewer_id,
    )
    lineage = compliance_service.get_submission_lineage(
        db, organisation_id=context.organisation.id, submission=submission
    )
    return compliance_service.submission_to_dict(
        submission,
        comparison=compliance_service.build_comparison(db, submission),
        all_revisions=lineage,
    )


@router.post(
    "/{submission_id}/decide",
    response_model=ContentSubmissionResponse,
    summary="Approve, reject, or request revisions on submitted marketing content",
)
def decide_approval(
    submission_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.APPROVAL_DECIDE)),
    db: Session = Depends(get_db),
):
    submission = compliance_service.decide_approval(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        submission_id=submission_id,
        decision=payload.decision,
        comments=payload.comments,
    )
    lineage = compliance_service.get_submission_lineage(
        db, organisation_id=context.organisation.id, submission=submission
    )
    return compliance_service.submission_to_dict(
        submission,
        comparison=compliance_service.build_comparison(db, submission),
        all_revisions=lineage,
    )


@router.post(
    "/{submission_id}/comments",
    response_model=ContentSubmissionResponse,
    summary="Add a reviewer comment or note to a content submission",
)
def add_comment(
    submission_id: uuid.UUID,
    payload: AddCommentRequest,
    context: TenantContext = Depends(require_permission(PermissionCode.CONTENT_REVIEW)),
    db: Session = Depends(get_db),
):
    submission = compliance_service.add_comment(
        db,
        organisation_id=context.organisation.id,
        user_id=context.user.id,
        submission_id=submission_id,
        comments=payload.comments,
    )
    lineage = compliance_service.get_submission_lineage(
        db, organisation_id=context.organisation.id, submission=submission
    )
    return compliance_service.submission_to_dict(
        submission,
        comparison=compliance_service.build_comparison(db, submission),
        all_revisions=lineage,
    )
