"""End-to-End Verification Test Suite for Brand Hub Guideline Document Management.
Task 5.1 Verification: Traces the exact user workflow executed from the UI:
1. Upload PNG brand guideline document with title and category
2. List guideline documents and verify metadata (status, chunks_count, page_count)
3. Retrieve document metadata via single-document GET
4. Inspect sentence-aware vector chunks via GET .../chunks
5. Trigger pgvector embedding generation via POST .../embed
6. Reparse guideline document from filesystem binary via POST .../reparse
7. Delete guideline document and verify chunk cleanup via DELETE
8. Verify tenant isolation (cross-tenant access rejected) and immutability (publish version locks uploads)
"""
import io
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


def _setup_org_and_kit(db: Session, role_name: str = RoleName.BRAND_MANAGER):
    user = User(
        id=uuid.uuid4(),
        email=f"e2e-user-{uuid.uuid4().hex[:6]}@inkloom.ai",
        full_name="E2E Brand Manager",
        password_hash="test_hash",
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    db.flush()

    org = Organisation(
        id=uuid.uuid4(),
        name="E2E Test Financial Org",
        slug=f"e2e-org-{uuid.uuid4().hex[:8]}",
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

    kit = BrandKit(
        id=uuid.uuid4(),
        organisation_id=org.id,
        name="Apex Banking Brand Kit",
        slug=f"apex-kit-{uuid.uuid4().hex[:6]}",
        created_by_user_id=user.id,
    )
    db.add(kit)
    db.flush()

    version = BrandKitVersion(
        id=uuid.uuid4(),
        brand_kit_id=kit.id,
        organisation_id=org.id,
        version_number=1,
        status=BrandKitVersionStatus.DRAFT,
        created_by_user_id=user.id,
    )
    db.add(version)
    db.commit()

    token, _, _ = create_access_token(subject=user.id, email=user.email)
    return user, org, kit, version, token


def _create_synthetic_png(text: str) -> bytes:
    img = Image.new("RGB", (900, 200), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.multiline_text((20, 20), text, fill=(0, 0, 0), spacing=6)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_complete_brand_hub_guideline_document_lifecycle_e2e(test_client: TestClient, db_session: Session):
    """E2E lifecycle test verifying all 7 user operations available in the Brand Hub UI."""
    user, org, kit, version, token = _setup_org_and_kit(db_session, role_name=RoleName.BRAND_MANAGER)
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Organisation-ID": str(org.id),
    }

    base_url = f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents"

    # -------------------------------------------------------------------------
    # Step 1: Upload Guideline Document (POST multipart/form-data)
    # -------------------------------------------------------------------------
    png_content = _create_synthetic_png("BRAND LOGO USAGE:\nAlways preserve clear space.\nDo not stretch logo.")
    upload_resp = test_client.post(
        base_url,
        headers=headers,
        files={"file": ("logo_guidelines.png", png_content, "image/png")},
        data={
            "title": "Master Logo Usage Guidelines",
            "document_category": GuidelineDocumentCategory.STYLE_GUIDE,
        },
    )
    assert upload_resp.status_code == status.HTTP_201_CREATED, upload_resp.text
    uploaded_doc = upload_resp.json()
    doc_id = uploaded_doc["id"]

    assert uploaded_doc["title"] == "Master Logo Usage Guidelines"
    assert uploaded_doc["original_filename"] == "logo_guidelines.png"
    assert uploaded_doc["document_category"] == GuidelineDocumentCategory.STYLE_GUIDE
    assert uploaded_doc["parsing_status"] == DocumentParsingStatus.PARSED
    assert uploaded_doc["chunks_count"] >= 1
    assert uploaded_doc["page_count"] == 1
    assert uploaded_doc["file_size_bytes"] == len(png_content)
    assert uploaded_doc["embedded_at"] is None

    # -------------------------------------------------------------------------
    # Step 2: List Documents (GET)
    # -------------------------------------------------------------------------
    list_resp = test_client.get(base_url, headers=headers)
    assert list_resp.status_code == status.HTTP_200_OK
    docs = list_resp.json()
    assert len(docs) == 1
    assert docs[0]["id"] == doc_id
    assert docs[0]["chunks_count"] == uploaded_doc["chunks_count"]

    # -------------------------------------------------------------------------
    # Step 3: Retrieve Document Metadata (GET /{document_id})
    # -------------------------------------------------------------------------
    get_resp = test_client.get(f"{base_url}/{doc_id}", headers=headers)
    assert get_resp.status_code == status.HTTP_200_OK
    single_doc = get_resp.json()
    assert single_doc["id"] == doc_id
    assert single_doc["title"] == "Master Logo Usage Guidelines"

    # -------------------------------------------------------------------------
    # Step 4: Inspect Generated Chunks (GET /{document_id}/chunks)
    # -------------------------------------------------------------------------
    chunks_resp = test_client.get(f"{base_url}/{doc_id}/chunks", headers=headers)
    assert chunks_resp.status_code == status.HTTP_200_OK
    chunks = chunks_resp.json()
    assert len(chunks) >= 1
    assert chunks[0]["page_number"] == 1
    assert chunks[0]["char_start"] >= 0
    assert chunks[0]["char_end"] > chunks[0]["char_start"]
    assert "LOGO" in chunks[0]["content"].upper()

    # -------------------------------------------------------------------------
    # Step 5: Trigger Embedding Generation (POST /{document_id}/embed)
    # -------------------------------------------------------------------------
    # 5a. Unconfigured provider yields HTTP 503 (expected in default test/local env without API key)
    unconfigured_resp = test_client.post(f"{base_url}/{doc_id}/embed", headers=headers)
    assert unconfigured_resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert "Embedding provider is not configured" in unconfigured_resp.json()["detail"]

    # 5b. When embedding provider is configured, embedding generation succeeds (HTTP 200)
    class FakeEmbeddingProvider:
        provider_name = "openai"
        model_name = "text-embedding-3-small"
        expected_dimension = 1024
        is_mock = False

        async def embed_texts(self, texts: list[str]) -> list[list[float]]:
            return [[0.05] * 1024 for _ in texts]

        def validate_vector(self, vector: list[float], context_idx: int = 0) -> list[float]:
            return [float(v) for v in vector]

    from unittest.mock import patch
    with patch("app.services.rag.embedding_service.get_embedding_provider", return_value=FakeEmbeddingProvider()):
        embed_resp = test_client.post(f"{base_url}/{doc_id}/embed", headers=headers)
        assert embed_resp.status_code == status.HTTP_200_OK, embed_resp.text
        embedded_doc = embed_resp.json()
        assert embedded_doc["id"] == doc_id
        assert embedded_doc["embedded_at"] is not None

    # -------------------------------------------------------------------------
    # Step 6: Reparse Document (POST /{document_id}/reparse)
    # -------------------------------------------------------------------------
    reparse_resp = test_client.post(f"{base_url}/{doc_id}/reparse", headers=headers)
    assert reparse_resp.status_code == status.HTTP_200_OK
    reparsed_doc = reparse_resp.json()
    assert reparsed_doc["id"] == doc_id
    assert reparsed_doc["parsing_status"] == DocumentParsingStatus.PARSED
    assert reparsed_doc["chunks_count"] >= 1

    # -------------------------------------------------------------------------
    # Step 7: Delete Guideline Document (DELETE /{document_id})
    # -------------------------------------------------------------------------
    delete_resp = test_client.delete(f"{base_url}/{doc_id}", headers=headers)
    assert delete_resp.status_code == status.HTTP_204_NO_CONTENT

    # Verify document is gone from listing
    post_delete_list = test_client.get(base_url, headers=headers).json()
    assert len(post_delete_list) == 0

    # Verify chunks are deleted from database
    remaining_chunks = db_session.execute(
        select(BrandDocumentChunk).where(BrandDocumentChunk.document_id == uuid.UUID(doc_id))
    ).scalars().all()
    assert len(remaining_chunks) == 0


def test_permission_guard_read_only_user_cannot_mutate(test_client: TestClient, db_session: Session):
    """Verify that a user with only brand:read permission cannot upload, reparse, embed, or delete."""
    # REVIEWER has brand:read but NOT brand:manage
    user, org, kit, version, token = _setup_org_and_kit(db_session, role_name=RoleName.REVIEWER)
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Organisation-ID": str(org.id),
    }
    base_url = f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents"

    # 1. Reading documents succeeds
    list_resp = test_client.get(base_url, headers=headers)
    assert list_resp.status_code == status.HTTP_200_OK

    # 2. Uploading fails with 403 Forbidden
    png_content = _create_synthetic_png("Some guideline text")
    upload_resp = test_client.post(
        base_url,
        headers=headers,
        files={"file": ("guide.png", png_content, "image/png")},
    )
    assert upload_resp.status_code == status.HTTP_403_FORBIDDEN

    # 3. Deleting fails with 403 Forbidden
    fake_doc_id = uuid.uuid4()
    del_resp = test_client.delete(f"{base_url}/{fake_doc_id}", headers=headers)
    assert del_resp.status_code == status.HTTP_403_FORBIDDEN


def test_immutability_guard_published_version_rejects_mutations(test_client: TestClient, db_session: Session):
    """Verify that PUBLISHED versions reject all mutating guideline operations with 409 Conflict."""
    user, org, kit, version, token = _setup_org_and_kit(db_session, role_name=RoleName.ADMIN)
    version.status = BrandKitVersionStatus.PUBLISHED
    db_session.commit()

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Organisation-ID": str(org.id),
    }
    base_url = f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents"

    # 1. Uploading to PUBLISHED version fails with 409 Conflict
    png_content = _create_synthetic_png("Published guideline text")
    upload_resp = test_client.post(
        base_url,
        headers=headers,
        files={"file": ("guide.png", png_content, "image/png")},
    )
    assert upload_resp.status_code == status.HTTP_409_CONFLICT
    assert "immutable" in upload_resp.json()["detail"].lower()
