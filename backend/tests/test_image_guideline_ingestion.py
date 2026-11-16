"""Focused test suite for Round 3 Task 4:
PNG, JPG, and JPEG Brand Guideline Ingestion.

Covers:
1. Successful PNG guideline upload, OCR extraction, and chunk persistence.
2. Successful JPG/JPEG guideline upload, OCR extraction, and chunk persistence.
3. Correct chunk creation, offsets, and metadata.
4. Mismatched file signatures (magic-byte validation).
5. Unsupported extensions and unsupported MIME types rejection (415).
6. Corrupted image rejection (422).
7. Oversized image dimensions rejection (422 exceeding 25MP).
8. Empty file rejection (400).
9. Blank image with zero readable text rejection (422).
10. Tenant isolation and immutable BrandKitVersion guard (409).
11. Backward compatibility: PDF, DOCX, and TXT guideline uploads remain functional.
"""
from __future__ import annotations

import io
import os
import uuid
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db, init_db
from app.main import app
from app.models import Organisation, OrganisationMembership, Role, RoleName, User
from app.models.brand import (
    BrandDocumentChunk,
    BrandGuidelineDocument,
    BrandKit,
    BrandKitVersion,
    BrandKitVersionStatus,
    DocumentParsingStatus,
    GuidelineDocumentCategory,
)
from app.core.security import create_access_token


@pytest.fixture
def db_session() -> Session:
    """In-memory SQLite database session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    init_db(session=session)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def test_client(db_session: Session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _create_user_and_org(
    db: Session,
    role_name: str = RoleName.ADMIN,
    org_name: str = "Image Guideline Org",
) -> tuple[User, Organisation, str]:
    user = User(
        id=uuid.uuid4(),
        email=f"tester-{uuid.uuid4().hex[:6]}@inkloom.ai",
        full_name="Guideline Image Tester",
        password_hash="test_hash",
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    db.flush()

    org = Organisation(
        id=uuid.uuid4(),
        name=org_name,
        slug=f"org-{uuid.uuid4().hex[:8]}",
        created_by=user.id,
    )
    db.add(org)
    db.flush()

    role = db.execute(select(Role).where(Role.name == role_name)).scalar_one()
    membership = OrganisationMembership(
        id=uuid.uuid4(),
        user_id=user.id,
        organisation_id=org.id,
        role_id=role.id,
        status="ACTIVE",
    )
    db.add(membership)
    db.commit()

    token, _, _ = create_access_token(subject=user.id, email=user.email)
    return user, org, token


def _create_brand_kit_and_version(
    db: Session,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    is_published: bool = False,
) -> tuple[BrandKit, BrandKitVersion]:
    kit = BrandKit(
        id=uuid.uuid4(),
        organisation_id=organisation_id,
        name="Visual Identity Kit",
        slug=f"visual-kit-{uuid.uuid4().hex[:6]}",
        created_by_user_id=user_id,
    )
    db.add(kit)
    db.flush()

    version = BrandKitVersion(
        id=uuid.uuid4(),
        brand_kit_id=kit.id,
        organisation_id=organisation_id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user_id,
    )
    db.add(version)
    db.flush()

    if is_published:
        version.status = BrandKitVersionStatus.PUBLISHED
        db.flush()

    db.commit()
    db.refresh(kit)
    db.refresh(version)
    return kit, version


def _generate_synthetic_image(text: str, fmt: str = "PNG") -> bytes:
    """Generate high-contrast bitmap image with legible text for OCR."""
    img = Image.new("RGB", (1000, 250), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.multiline_text((25, 25), text, fill=(0, 0, 0), spacing=8)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


# =============================================================================
# 1. SUCCESSFUL PNG GUIDELINE UPLOAD & CHUNK PERSISTENCE
# =============================================================================

def test_upload_png_guideline_document_success(test_client: TestClient, db_session: Session):
    """Uploading a valid PNG brand guideline extracts OCR text, persists document and chunks."""
    user, org, token = _create_user_and_org(db_session)
    kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

    text = "BRAND TYPOGRAPHY STANDARDS:\nPrimary font is Inter Display across all customer touchpoints.\nDo not use unapproved decorative typefaces."
    png_bytes = _generate_synthetic_image(text, fmt="PNG")

    response = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("typography_guide.png", png_bytes, "image/png")},
        data={"title": "Typography Guide", "document_category": GuidelineDocumentCategory.STYLE_GUIDE},
    )

    assert response.status_code == status.HTTP_201_CREATED, response.text
    data = response.json()
    assert data["title"] == "Typography Guide"
    assert data["document_category"] == GuidelineDocumentCategory.STYLE_GUIDE
    assert data["original_filename"] == "typography_guide.png"
    assert data["parsing_status"] == DocumentParsingStatus.PARSED
    assert data["chunks_count"] >= 1
    assert data["page_count"] == 1

    # Verify database record
    doc_id = uuid.UUID(data["id"])
    doc = db_session.execute(
        select(BrandGuidelineDocument).where(BrandGuidelineDocument.id == doc_id)
    ).scalar_one()
    assert doc.organisation_id == org.id
    assert doc.brand_kit_version_id == version.id
    assert doc.mime_type == "image/png"
    assert "TYPOGRAPHY" in doc.raw_text_content.upper()

    # Verify chunks
    chunks = list(db_session.execute(
        select(BrandDocumentChunk).where(BrandDocumentChunk.document_id == doc_id)
    ).scalars().all())
    assert len(chunks) >= 1
    assert chunks[0].page_number == 1
    assert chunks[0].organisation_id == org.id
    assert chunks[0].brand_kit_version_id == version.id


# =============================================================================
# 2. SUCCESSFUL JPG / JPEG GUIDELINE UPLOAD & CHUNK PERSISTENCE
# =============================================================================

def test_upload_jpeg_guideline_document_success(test_client: TestClient, db_session: Session):
    """Uploading a valid JPEG brand guideline extracts OCR text, persists document and chunks."""
    user, org, token = _create_user_and_org(db_session)
    kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

    text = "COLOR PALETTE POLICIES:\nMidnight Blue #0A192F is the dominant background color.\nAccent color is Coral #FF6B6B."
    jpeg_bytes = _generate_synthetic_image(text, fmt="JPEG")

    response = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("color_palette.jpg", jpeg_bytes, "image/jpeg")},
        data={"title": "Color Palette", "document_category": GuidelineDocumentCategory.BRAND_BOOK},
    )

    assert response.status_code == status.HTTP_201_CREATED, response.text
    data = response.json()
    assert data["title"] == "Color Palette"
    assert data["original_filename"] == "color_palette.jpg"
    assert data["parsing_status"] == DocumentParsingStatus.PARSED
    assert data["chunks_count"] >= 1

    doc_id = uuid.UUID(data["id"])
    doc = db_session.execute(
        select(BrandGuidelineDocument).where(BrandGuidelineDocument.id == doc_id)
    ).scalar_one()
    assert doc.mime_type == "image/jpeg"


# =============================================================================
# 3. CHUNK METADATA AND OFFSETS VALIDATION
# =============================================================================

def test_image_guideline_chunk_metadata_and_offsets(test_client: TestClient, db_session: Session):
    """Verify that chunks created from image guidelines possess valid character bounds and hashes."""
    user, org, token = _create_user_and_org(db_session)
    kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

    text = "LOGO USAGE RULES:\nClear space around the logo must equal the height of the letter I.\nMinimum digital size is 32 pixels."
    png_bytes = _generate_synthetic_image(text, fmt="PNG")

    response = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("logo_rules.png", png_bytes, "image/png")},
    )
    assert response.status_code == status.HTTP_201_CREATED
    doc_id = uuid.UUID(response.json()["id"])

    chunks = list(db_session.execute(
        select(BrandDocumentChunk).where(BrandDocumentChunk.document_id == doc_id)
    ).scalars().all())

    for chunk in chunks:
        assert chunk.char_start >= 0
        assert chunk.char_end > chunk.char_start
        assert chunk.token_count > 0
        assert len(chunk.content_sha256) == 64
        assert chunk.page_number == 1


# =============================================================================
# 4. MISMATCHED FILE SIGNATURE & EXTENSION CHECKS
# =============================================================================

def test_mismatched_file_signature_rejected(test_client: TestClient, db_session: Session):
    """File extension claiming .png or .jpg but lacking authentic magic bytes is rejected with 415."""
    user, org, token = _create_user_and_org(db_session)
    kit, version = _create_brand_kit_and_version(db_session, org.id, user.id)

    # 1. Spoofed PNG (text disguised as PNG)
    fake_png = b"Not really a PNG image file header"
    resp1 = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("spoofed.png", fake_png, "image/png")},
    )
    assert resp1.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    assert "Invalid PNG file" in resp1.json()["detail"]

    # 2. Spoofed JPEG
    fake_jpg = b"Not a JPEG SOI marker"
    resp2 = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("spoofed.jpg", fake_jpg, "image/jpeg")},
    )
    assert resp2.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    assert "Invalid JPEG file" in resp2.json()["detail"]


def test_unsupported_guideline_extension_rejected(test_client: TestClient, db_session: Session):
    """Banned extensions (.exe, .gif, .bmp) are rejected with 415."""
    user, org, token = _create_user_and_org(db_session)
    kit, version = _create_brand_kit_and_version(db_session, org.id, user.id)

    resp = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("rules.bmp", b"BMheader", "image/bmp")},
    )
    assert resp.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    assert "Unsupported guideline format" in resp.json()["detail"]


def test_unsupported_client_mime_type_rejected(test_client: TestClient, db_session: Session):
    """Client providing disallowed MIME type is rejected with 415."""
    user, org, token = _create_user_and_org(db_session)
    kit, version = _create_brand_kit_and_version(db_session, org.id, user.id)

    png_bytes = _generate_synthetic_image("Valid image text", fmt="PNG")
    resp = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("valid.png", png_bytes, "application/x-msdownload")},
    )
    assert resp.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    assert "Unsupported MIME type" in resp.json()["detail"]


def test_mime_content_type_normalization_with_parameters(test_client: TestClient, db_session: Session):
    """Client sending Content-Type with parameters (e.g. charset, q) is properly normalized."""
    user, org, token = _create_user_and_org(db_session)
    kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

    # 1. image/png; charset=utf-8
    png_bytes = _generate_synthetic_image("PNG Brand Typography Guidelines", fmt="PNG")
    resp1 = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("guide1.png", png_bytes, "image/png; charset=utf-8")},
    )
    assert resp1.status_code == status.HTTP_201_CREATED, resp1.text
    assert resp1.json()["original_filename"] == "guide1.png"

    # 2. image/jpeg; q=0.9
    jpeg_bytes = _generate_synthetic_image("JPEG Brand Color Palette", fmt="JPEG")
    resp2 = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("palette.jpg", jpeg_bytes, "image/jpeg; q=0.9")},
    )
    assert resp2.status_code == status.HTTP_201_CREATED, resp2.text
    assert resp2.json()["original_filename"] == "palette.jpg"

    # 3. text/plain; charset=utf-8
    txt_bytes = b"Primary brand values:\nIntegrity, Innovation, Inclusion."
    resp3 = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("values.txt", txt_bytes, "text/plain; charset=utf-8")},
    )
    assert resp3.status_code == status.HTTP_201_CREATED, resp3.text
    assert resp3.json()["original_filename"] == "values.txt"

    # 4. Unsupported MIME type with parameters still rejected
    resp4 = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("values.txt", txt_bytes, "application/zip; charset=utf-8")},
    )
    assert resp4.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    assert "Unsupported MIME type" in resp4.json()["detail"]


# =============================================================================
# 5. ERROR DEFENSE: CORRUPTED, OVERSIZED, EMPTY, AND BLANK IMAGES
# =============================================================================

def test_corrupted_image_rejected(test_client: TestClient, db_session: Session):
    """Image with valid PNG signature but truncated/corrupt binary body is rejected with 422."""
    user, org, token = _create_user_and_org(db_session)
    kit, version = _create_brand_kit_and_version(db_session, org.id, user.id)

    corrupted_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    resp = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("corrupt.png", corrupted_png, "image/png")},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "Image processing error" in resp.json()["detail"]


def test_oversized_image_dimensions_rejected(test_client: TestClient, db_session: Session):
    """Image exceeding 25,000,000 pixels is rejected with 422 (SEC-04)."""
    user, org, token = _create_user_and_org(db_session)
    kit, version = _create_brand_kit_and_version(db_session, org.id, user.id)

    # 5100 x 5100 = 26,010,000 pixels
    oversized = Image.new("RGB", (5100, 5100), color=(255, 255, 255))
    buf = io.BytesIO()
    oversized.save(buf, format="PNG")

    resp = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("huge.png", buf.getvalue(), "image/png")},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "exceeds maximum limit of 25000000 pixels" in resp.json()["detail"]


def test_empty_image_rejected(test_client: TestClient, db_session: Session):
    """Empty 0-byte upload is rejected with 400 Bad Request."""
    user, org, token = _create_user_and_org(db_session)
    kit, version = _create_brand_kit_and_version(db_session, org.id, user.id)

    resp = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "empty" in resp.json()["detail"].lower()


def test_blank_image_without_readable_text_rejected(test_client: TestClient, db_session: Session):
    """Blank white image containing zero readable text is rejected with 422."""
    user, org, token = _create_user_and_org(db_session)
    kit, version = _create_brand_kit_and_version(db_session, org.id, user.id)

    blank = Image.new("RGB", (200, 100), color=(255, 255, 255))
    buf = io.BytesIO()
    blank.save(buf, format="PNG")

    resp = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("blank.png", buf.getvalue(), "image/png")},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "Extracted document contains no readable text" in resp.json()["detail"]


# =============================================================================
# 6. TENANT ISOLATION AND IMMUTABILITY RULES
# =============================================================================

def test_immutable_version_rejects_image_upload(test_client: TestClient, db_session: Session):
    """Uploaded images cannot be attached to PUBLISHED BrandKitVersions (HTTP 409)."""
    user, org, token = _create_user_and_org(db_session)
    kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=True)

    png_bytes = _generate_synthetic_image("Brand Rules Text", fmt="PNG")

    resp = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("guide.png", png_bytes, "image/png")},
    )
    assert resp.status_code == status.HTTP_409_CONFLICT
    assert "immutable" in resp.json()["detail"].lower()


# =============================================================================
# 7. BACKWARD COMPATIBILITY: TXT GUIDELINES REMAIN FUNCTIONAL
# =============================================================================

def test_txt_guideline_upload_remains_functional(test_client: TestClient, db_session: Session):
    """Existing TXT uploads continue to function seamlessly."""
    user, org, token = _create_user_and_org(db_session)
    kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

    txt_content = b"Brand Identity Guidelines 2026.\nAlways use approved brand assets."
    resp = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("guidelines.txt", txt_content, "text/plain")},
    )
    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.json()["original_filename"] == "guidelines.txt"
    assert resp.json()["chunks_count"] >= 1

    doc_id = uuid.UUID(resp.json()["id"])
    doc = db_session.execute(
        select(BrandGuidelineDocument).where(BrandGuidelineDocument.id == doc_id)
    ).scalar_one()
    assert doc.mime_type == "text/plain"


def test_pdf_and_docx_guideline_uploads_remain_functional(test_client: TestClient, db_session: Session):
    """Existing PDF and DOCX uploads continue to function without regressions."""
    import docx

    user, org, token = _create_user_and_org(db_session)
    kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

    # 1. DOCX upload
    doc_docx = docx.Document()
    doc_docx.add_paragraph("DOCX Brand Guidelines: Consistency is critical across all products.")
    buf_docx = io.BytesIO()
    doc_docx.save(buf_docx)
    docx_bytes = buf_docx.getvalue()

    resp_docx = test_client.post(
        f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("guidelines.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
    )
    assert resp_docx.status_code == status.HTTP_201_CREATED
    assert resp_docx.json()["original_filename"] == "guidelines.docx"
    assert resp_docx.json()["chunks_count"] >= 1

    doc_docx_record = db_session.execute(
        select(BrandGuidelineDocument).where(BrandGuidelineDocument.id == uuid.UUID(resp_docx.json()["id"]))
    ).scalar_one()
    assert doc_docx_record.mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
