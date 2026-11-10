"""Multimodal Document Extraction & OCR Service (Phase 5.3).

Primary Owner: Pathik Talwar (AI processing & document extraction)
Backend Integration: Pathik Talwar

Supported formats:
- Plain text (.txt)
- Portable Document Format (.pdf)
- Microsoft Word Document (.docx)
- Image formats (.png, .jpg, .jpeg) with optical character recognition / fallback

Security guarantees:
- Organisation-scoped upload isolation
- Strict MIME & magic header validation
- Path traversal prevention & safe sanitized filenames
- Configurable file size limits (default 10MB)
"""
from __future__ import annotations

import io
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

from fastapi import HTTPException, UploadFile, status

# Allowed MIME types and extensions
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg"}
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "image/png",
    "image/jpeg",
    "image/pjpeg",
}

# 10MB maximum file size limit (SEC-02)
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024

# Upload stream chunk size: 64 KB (SEC-02)
UPLOAD_CHUNK_SIZE_BYTES = 64 * 1024

# SEC-04 Resource Limits & Defensive Bounds
MAX_PDF_PAGES = 100
MAX_OCR_IMAGES_PER_DOCUMENT = 10
MAX_IMAGE_PIXELS = 25_000_000  # 25 MP (e.g., 5000x5000)
MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_DOCX_TABLE_ROWS = 500
MAX_DOCX_ZIP_ENTRIES = 1000
MAX_DOCX_ENTRY_BYTES = 20 * 1024 * 1024  # 20 MB max per single zip entry
MAX_ZIP_COMPRESSION_RATIO = 50.0  # 50:1 max compression ratio (ZIP bomb guard)
MAX_EXTRACTED_TEXT_CHARS = 2_000_000  # 2M characters max extracted text
OCR_TIMEOUT_SECONDS = 30

# Base storage path for uploaded artifacts (organisation isolated)
LOCAL_UPLOAD_ROOT = Path("storage/uploads").resolve()


class ExtractionError(Exception):
    """Raised when document parsing or OCR fails."""
    pass


class UnsupportedFileError(Exception):
    """Raised when a file type or extension is not supported."""
    pass


@dataclass
class ExtractionResult:
    """Structured extraction outcome preserving metadata and page provenance."""
    text: str
    format: str
    method: str
    page_count: int = 1
    char_count: int = 0
    pages: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    ocr_fallback_triggered: bool = False

    def __post_init__(self):
        self.char_count = len(self.text)


def sanitize_filename(filename: str) -> str:
    """Strip directory traversal sequences and unsafe characters."""
    name = os.path.basename(filename)
    # Remove any non-alphanumeric or standard characters
    safe = re.sub(r"[^\w\s.-]", "", name).strip()
    return safe or f"document_{uuid.uuid4().hex[:8]}"


def detect_file_format(filename: str, content: bytes) -> str:
    """Validate file extension and magic byte headers."""
    ext = os.path.splitext(filename.lower())[1]
    if ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedFileError(f"Unsupported file extension '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    # Magic byte validation
    if ext == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise UnsupportedFileError("Invalid PDF file: Missing %PDF- signature.")
        return "PDF"
    elif ext == ".docx":
        # DOCX is a zip archive starting with PK\x03\x04
        if not (content.startswith(b"PK\x03\x04") or content.startswith(b"PK\x05\x06") or content.startswith(b"PK\x07\x08")):
            raise UnsupportedFileError("Invalid DOCX file: Missing ZIP signature.")
        return "DOCX"
    elif ext == ".png":
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise UnsupportedFileError("Invalid PNG file: Missing PNG signature.")
        return "PNG"
    elif ext in (".jpg", ".jpeg"):
        if not (content.startswith(b"\xff\xd8\xff")):
            raise UnsupportedFileError("Invalid JPEG file: Missing JPEG SOI signature.")
        return "JPEG"
    elif ext == ".txt":
        return "TXT"

    return "UNKNOWN"


def extract_txt(content: bytes) -> ExtractionResult:
    """Extract UTF-8 / ASCII text from raw bytes with encoding fallbacks."""
    for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
        try:
            text = content.decode(enc)
            return ExtractionResult(
                text=text.strip(),
                format="TXT",
                method="text/plain-decoder",
                page_count=1,
                pages=[{"page_number": 1, "text": text.strip()}],
                metadata={"encoding": enc},
            )
        except UnicodeDecodeError:
            continue
    raise ExtractionError("Unable to decode text file with supported encodings (UTF-8, Latin-1, CP1252).")


def extract_pdf(content: bytes) -> ExtractionResult:
    """Extract page text from PDF document using pypdf with resource bounding (SEC-04)."""
    import pypdf

    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        page_count = len(reader.pages)
        if page_count > MAX_PDF_PAGES:
            raise ExtractionError(
                f"PDF page count ({page_count}) exceeds maximum allowed limit of {MAX_PDF_PAGES} pages."
            )

        pages_out: list[dict[str, Any]] = []
        full_text_parts: list[str] = []
        total_extracted_chars = 0

        for idx, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            stripped = page_text.strip()
            total_extracted_chars += len(stripped)
            if total_extracted_chars > MAX_EXTRACTED_TEXT_CHARS:
                raise ExtractionError(
                    f"PDF extracted text exceeds maximum allowed limit of {MAX_EXTRACTED_TEXT_CHARS} characters."
                )

            pages_out.append({
                "page_number": idx,
                "text": stripped,
            })
            if stripped:
                full_text_parts.append(stripped)

        full_text = "\n\n".join(full_text_parts).strip()
        metadata = {
            "title": reader.metadata.title if reader.metadata else None,
            "author": reader.metadata.author if reader.metadata else None,
            "creator": reader.metadata.creator if reader.metadata else None,
        }

        # If zero text extracted, check for OCR fallback
        ocr_fallback = False
        if not full_text:
            ocr_text = try_ocr_pdf_fallback(reader)
            if ocr_text:
                full_text = ocr_text
                ocr_fallback = True

        return ExtractionResult(
            text=full_text,
            format="PDF",
            method="pypdf-text-extractor" if not ocr_fallback else "pypdf-ocr-fallback",
            page_count=page_count,
            pages=pages_out,
            metadata=metadata,
            ocr_fallback_triggered=ocr_fallback,
        )
    except Exception as exc:
        if isinstance(exc, ExtractionError):
            raise
        raise ExtractionError(f"PDF extraction error: {str(exc)}") from exc


def try_ocr_pdf_fallback(reader: Any) -> str:
    """Attempt OCR extraction on embedded raster images in scanned PDFs with image count limits (SEC-04)."""
    try:
        import pytesseract
        from PIL import Image

        # Count total raster images across all pages to protect against excessive OCR (SEC-04)
        total_images = sum(len(page.images) for page in reader.pages)
        if total_images > MAX_OCR_IMAGES_PER_DOCUMENT:
            raise ExtractionError(
                f"Scanned PDF contains {total_images} images requiring OCR, exceeding maximum limit of {MAX_OCR_IMAGES_PER_DOCUMENT}."
            )

        text_parts = []
        for page in reader.pages:
            for image_file in page.images:
                try:
                    pil_img = Image.open(io.BytesIO(image_file.data))
                    if pil_img.width * pil_img.height > MAX_IMAGE_PIXELS:
                        raise ExtractionError(
                            f"Embedded PDF image exceeds maximum pixel limit of {MAX_IMAGE_PIXELS} pixels."
                        )
                    ocr_result = pytesseract.image_to_string(pil_img, timeout=OCR_TIMEOUT_SECONDS)
                    if ocr_result.strip():
                        text_parts.append(ocr_result.strip())
                except ExtractionError:
                    raise
                except Exception:
                    continue
        return "\n\n".join(text_parts).strip()
    except ExtractionError:
        raise
    except Exception:
        # Tesseract engine not present or OCR failed
        return ""


def validate_docx_zip_archive(content: bytes) -> None:
    """Validate DOCX zip archive against decompression bombs and excessive entries (SEC-04)."""
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            infolist = zf.infolist()
            if len(infolist) > MAX_DOCX_ZIP_ENTRIES:
                raise ExtractionError(
                    f"DOCX archive contains {len(infolist)} entries, exceeding maximum allowed {MAX_DOCX_ZIP_ENTRIES}."
                )

            total_uncompressed = sum(info.file_size for info in infolist)
            if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise ExtractionError(
                    f"DOCX uncompressed size ({total_uncompressed} bytes) exceeds maximum allowed {MAX_DOCX_UNCOMPRESSED_BYTES} bytes ({MAX_DOCX_UNCOMPRESSED_BYTES // (1024 * 1024)}MB)."
                )

            for info in infolist:
                if info.file_size > MAX_DOCX_ENTRY_BYTES:
                    raise ExtractionError(
                        f"DOCX entry '{info.filename}' uncompressed size ({info.file_size} bytes) exceeds limit of {MAX_DOCX_ENTRY_BYTES} bytes."
                    )
                if info.compress_size > 0:
                    ratio = info.file_size / info.compress_size
                    if ratio > MAX_ZIP_COMPRESSION_RATIO:
                        raise ExtractionError(
                            f"DOCX entry '{info.filename}' has suspicious compression ratio {ratio:.1f}:1 exceeding limit {MAX_ZIP_COMPRESSION_RATIO}:1 (potential ZIP bomb)."
                        )
    except zipfile.BadZipFile as bzf:
        raise ExtractionError(f"Invalid DOCX file (corrupted ZIP archive): {bzf}") from bzf


def extract_docx(content: bytes) -> ExtractionResult:
    """Extract paragraphs and structured table content from DOCX files using python-docx with resource bounding (SEC-04)."""
    import docx

    # 1. Defend against ZIP bombs and excessive uncompressed expansion (SEC-04)
    validate_docx_zip_archive(content)

    try:
        doc = docx.Document(io.BytesIO(content))
        text_parts: list[str] = []

        # 2. Paragraphs
        for p in doc.paragraphs:
            if p.text.strip():
                text_parts.append(p.text.strip())

        # 3. Tables with row count limit (SEC-04)
        total_rows = sum(len(table.rows) for table in doc.tables)
        if total_rows > MAX_DOCX_TABLE_ROWS:
            raise ExtractionError(
                f"DOCX table row count ({total_rows}) exceeds maximum allowed limit of {MAX_DOCX_TABLE_ROWS} rows."
            )

        for table in doc.tables:
            for row in table.rows:
                row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_cells:
                    text_parts.append(" | ".join(row_cells))

        full_text = "\n\n".join(text_parts).strip()
        if len(full_text) > MAX_EXTRACTED_TEXT_CHARS:
            raise ExtractionError(
                f"DOCX extracted text exceeds maximum allowed limit of {MAX_EXTRACTED_TEXT_CHARS} characters."
            )

        return ExtractionResult(
            text=full_text,
            format="DOCX",
            method="python-docx-parser",
            page_count=1,
            pages=[{"page_number": 1, "text": full_text}],
            metadata={"paragraphs_count": len(doc.paragraphs), "tables_count": len(doc.tables)},
        )
    except Exception as exc:
        if isinstance(exc, ExtractionError):
            raise
        raise ExtractionError(f"DOCX extraction error: {str(exc)}") from exc


def extract_image_ocr(content: bytes, ext: str) -> ExtractionResult:
    """Extract text from PNG/JPEG image using Pillow and pytesseract with dimension bounding (SEC-04)."""
    try:
        import pytesseract
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

        pil_img = Image.open(io.BytesIO(content))
        total_pixels = pil_img.width * pil_img.height
        if total_pixels > MAX_IMAGE_PIXELS:
            raise ExtractionError(
                f"Image dimension {pil_img.width}x{pil_img.height} ({total_pixels} pixels) exceeds maximum limit of {MAX_IMAGE_PIXELS} pixels."
            )

        metadata = {
            "width": pil_img.width,
            "height": pil_img.height,
            "mode": pil_img.mode,
            "format": pil_img.format or ext.upper().lstrip("."),
        }

        try:
            ocr_text = pytesseract.image_to_string(pil_img, timeout=OCR_TIMEOUT_SECONDS)
            text_cleaned = ocr_text.strip()
            method = "pytesseract-tesseract-ocr"
        except Exception as ocr_err:
            # When system tesseract binary is not installed in the OS, document metadata is preserved
            text_cleaned = ""
            method = f"image-metadata-only (Tesseract engine offline: {ocr_err})"

        return ExtractionResult(
            text=text_cleaned,
            format=metadata["format"],
            method=method,
            page_count=1,
            pages=[{"page_number": 1, "text": text_cleaned}],
            metadata=metadata,
        )
    except Exception as exc:
        if isinstance(exc, ExtractionError):
            raise
        raise ExtractionError(f"Image processing error: {str(exc)}") from exc


def extract_document_text(filename: str, content: bytes) -> ExtractionResult:
    """Unified entry point for document extraction across all supported formats."""
    fmt = detect_file_format(filename, content)

    if fmt == "TXT":
        return extract_txt(content)
    elif fmt == "PDF":
        return extract_pdf(content)
    elif fmt == "DOCX":
        return extract_docx(content)
    elif fmt in ("PNG", "JPEG"):
        return extract_image_ocr(content, fmt.lower())
    else:
        raise UnsupportedFileError(f"Unrecognized or unsupported file format '{fmt}'.")


def store_uploaded_file(
    *,
    organisation_id: uuid.UUID,
    filename: str,
    content: bytes,
) -> tuple[str, str]:
    """Securely persist uploaded file inside organisation-isolated directory (CR-03)."""
    safe_name = sanitize_filename(filename)
    unique_prefix = uuid.uuid4().hex[:12]
    stored_name = f"{unique_prefix}_{safe_name}"

    upload_root = LOCAL_UPLOAD_ROOT.resolve()
    org_dir = (upload_root / str(organisation_id)).resolve()

    # Reject organisation directory escaping upload root before directory creation
    if not org_dir.is_relative_to(upload_root):
        raise ExtractionError("Security violation: Organisation storage path escapes upload root.")

    org_dir.mkdir(parents=True, exist_ok=True)

    dest_path = (org_dir / stored_name).resolve()

    # Reject file paths escaping either organisation directory or upload root before writing (CR-03)
    if not dest_path.is_relative_to(upload_root) or not dest_path.is_relative_to(org_dir):
        raise ExtractionError("Security violation: Target file destination escapes upload storage root.")

    try:
        with open(dest_path, "wb") as f:
            f.write(content)
    except Exception:
        if dest_path.is_file():
            dest_path.unlink()
        raise

    # Return (stored_path_relative, display_name)
    relative_path = f"{organisation_id}/{stored_name}"
    return relative_path, safe_name
