"""Tests for Inkloom AI Phase 6.1: Guideline Document Ingestion & Sentence-Aware Chunking.

Covers:
- Upload validation (PDF, DOCX, TXT formats, 10MB limits, empty files, unsupported extensions).
- Multi-tenant and Brand-Kit-scoped authorization and isolation.
- Immutability enforcement (DRAFT-only mutations, rejection on PUBLISHED versions).
- Sentence-aware sliding-window chunking (char offsets, SHA-256 hashes, token counts, overlap).
- Deletion and orphaned file cleanup (SEC-06, CR-03).
- Reparsing workflow on DRAFT versions.
"""
import hashlib
import io
import uuid
from pathlib import Path
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.main import app
from app.models import (
    BrandDocumentChunk,
    BrandGuidelineDocument,
    BrandKit,
    BrandKitVersion,
    BrandKitVersionStatus,
    DocumentParsingStatus,
    GuidelineDocumentCategory,
    Organisation,
    OrganisationMembership,
    Role,
    RoleName,
    User,
)
from app.services import document_extraction_service as doc_service
from app.services.rag import chunking_service


def _create_user_and_org(
    db: Session,
    *,
    email: str = "creator@example.com",
    org_name: str = "Acme Corp",
    role_name: str = RoleName.ADMIN,
) -> tuple[User, Organisation, str]:
    """Helper to create user, organisation, membership, and return bearer token."""
    user = User(
        id=uuid.uuid4(),
        email=email,
        full_name="Test User",
        password_hash="test_hash_not_used",
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

    token, _, _ = create_access_token(
        subject=user.id,
        email=user.email,
    )
    return user, org, token


def _create_brand_kit_and_version(
    db: Session,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    is_published: bool = False,
) -> tuple[BrandKit, BrandKitVersion]:
    """Helper to create brand kit and version (DRAFT or PUBLISHED)."""
    kit = BrandKit(
        id=uuid.uuid4(),
        organisation_id=organisation_id,
        name="Test Brand Kit",
        slug=f"test-kit-{uuid.uuid4().hex[:6]}",
        created_by_user_id=user_id,
    )
    db.add(kit)
    db.flush()

    # BrandKitVersion must be created as DRAFT first
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


def _generate_synthetic_pdf(pages_text: list[str]) -> bytes:
    """Generate minimal valid PDF binary with selectable text across arbitrary pages."""
    buf = io.BytesIO()
    kids = []
    objects = {}
    next_id = 3
    font_id = next_id
    objects[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    next_id += 1
    for t in pages_text:
        content_id = next_id
        next_id += 1
        page_id = next_id
        next_id += 1
        # Escape parenthesis in text for PDF literal string
        safe_t = t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 50 700 Td ({safe_t}) Tj ET".encode("latin1")
        objects[content_id] = f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream"
        objects[page_id] = f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode("ascii")
        kids.append(f"{page_id} 0 R")
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids_s = " ".join(kids)
    objects[2] = f"<< /Type /Pages /Kids [{kids_s}] /Count {len(kids)} >>".encode("ascii")
    buf.write(b"%PDF-1.4\n")
    xref = {}
    for oid in sorted(objects.keys()):
        xref[oid] = buf.tell()
        buf.write(f"{oid} 0 obj\n".encode("ascii") + objects[oid] + b"\nendobj\n")
    xref_pos = buf.tell()
    buf.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for oid in range(1, len(objects) + 1):
        buf.write(f"{xref[oid]:010d} 00000 n \n".encode("ascii"))
    buf.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode("ascii"))
    return buf.getvalue()


def _generate_synthetic_docx(paragraphs: list[str]) -> bytes:
    """Generate minimal valid DOCX binary with paragraphs."""
    import docx
    doc = docx.Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


class TestSentenceAwareChunking:
    """Unit tests for sentence-aware sliding-window chunking service."""

    def test_chunking_with_sentence_boundaries_and_overlap(self):
        sample_text = (
            "Inkloom AI is an enterprise brand compliance platform. "
            "It validates marketing content against approved brand policies and guideline documents. "
            "Every finding cites an exact character offset and verified evidence chunk. "
            "Unsupported statements are explicitly marked as unverified claims rather than hallucinated citations. "
            "Our primary brand colors are Navy Blue and Titanium Silver. "
            "Always include mandatory disclaimers for financial marketing materials."
        )

        specs = chunking_service.generate_chunk_specs(
            sample_text,
            target_tokens=25,
            overlap_tokens=8,
        )

        assert len(specs) >= 2
        for i, s in enumerate(specs):
            assert s.chunk_index == i
            assert s.char_start >= 0
            assert s.char_end > s.char_start
            assert s.token_count > 0
            assert len(s.content_sha256) == 64
            # Content matches the slice
            assert s.content == sample_text[s.char_start:s.char_end]

        # Verify sliding window overlap exists between consecutive chunks
        first_chunk = specs[0]
        second_chunk = specs[1]
        assert second_chunk.char_start < first_chunk.char_end

    def test_chunking_empty_text_returns_empty_list(self):
        specs = chunking_service.generate_chunk_specs("   \n\t  ")
        assert specs == []

    def test_chunk_orm_creation_satisfies_constraints(self):
        doc_id = uuid.uuid4()
        ver_id = uuid.uuid4()
        org_id = uuid.uuid4()

        sample_text = "This is a simple guideline policy sentence. All claims must be verified."
        chunks = chunking_service.chunk_document_text(
            text=sample_text,
            document_id=doc_id,
            brand_kit_version_id=ver_id,
            organisation_id=org_id,
            target_tokens=50,
            overlap_tokens=10,
        )

        assert len(chunks) == 1
        c = chunks[0]
        assert c.document_id == doc_id
        assert c.brand_kit_version_id == ver_id
        assert c.organisation_id == org_id
        assert c.chunk_index == 0
        assert c.embedding_dimension == 1024
        assert c.embedding is None
        assert c.token_count > 0

    def test_multipage_pdf_page_attribution_and_separator_drift(self):
        """CR-61-03: Verify multi-page PDF chunk offsets account for '\n\n' page separators."""
        page_texts = [
            "Page 1: Brand mission statement. We provide premier financial software solutions across India.",
            "Page 2: Prohibited terms. Never promise guaranteed returns or risk-free investment outcomes.",
            "Page 3: Mandatory disclaimers. Terms and conditions apply. Past performance is no guarantee of future results.",
        ]
        pdf_bytes = _generate_synthetic_pdf(page_texts)
        res = doc_service.extract_document_text("multi_page_guidelines.pdf", pdf_bytes)
        assert res.page_count == 3
        assert len(res.pages) == 3

        specs = chunking_service.generate_chunk_specs(
            res.text,
            target_tokens=20,
            overlap_tokens=5,
            page_metadata=res.pages,
        )

        assert len(specs) >= 3
        # Check that page attribution maps accurately to pages 1, 2, and 3
        attributed_pages = {s.page_number for s in specs}
        assert 1 in attributed_pages
        assert 2 in attributed_pages
        assert 3 in attributed_pages

        # Verify exact slice match for every chunk across page boundaries
        for s in specs:
            assert s.content == res.text[s.char_start:s.char_end]


class TestGuidelineDocumentUploadEndpoints:
    """Integration tests for guideline document upload, list, delete, and reparse."""

    def test_upload_txt_guideline_document_success(self, db_session: Session):
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session, role_name=RoleName.ADMIN)
        kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        content = b"Brand Identity Guidelines 2026.\nAlways use approved typography and brand colors."
        response = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("guideline.txt", content, "text/plain")},
            data={"title": "Primary Brand Guide", "document_category": GuidelineDocumentCategory.STYLE_GUIDE},
        )

        assert response.status_code == status.HTTP_201_CREATED, response.text
        data = response.json()
        assert data["title"] == "Primary Brand Guide"
        assert data["document_category"] == GuidelineDocumentCategory.STYLE_GUIDE
        assert data["original_filename"] == "guideline.txt"
        assert data["file_size_bytes"] == len(content)
        assert data["parsing_status"] == DocumentParsingStatus.PARSED
        assert data["chunks_count"] >= 1

        # Verify database persistence
        doc = db_session.execute(
            select(BrandGuidelineDocument).where(BrandGuidelineDocument.id == uuid.UUID(data["id"]))
        ).scalar_one()
        assert doc.brand_kit_version_id == version.id
        assert doc.organisation_id == org.id

        # Verify chunks persistence
        chunks = db_session.execute(
            select(BrandDocumentChunk).where(BrandDocumentChunk.document_id == doc.id)
        ).scalars().all()
        assert len(chunks) >= 1
        assert chunks[0].embedding_dimension == 1024

        # Clean up created file
        file_dest = doc_service.LOCAL_UPLOAD_ROOT / doc.storage_path
        if file_dest.is_file():
            file_dest.unlink()

    def test_upload_empty_file_fails_400(self, db_session: Session):
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        response = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("empty.txt", b"", "text/plain")},
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "empty" in response.json()["detail"].lower()

    def test_upload_unsupported_extension_fails_415(self, db_session: Session):
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        response = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("malicious.exe", b"MZexecutable", "application/octet-stream")},
        )
        assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE

    def test_upload_to_published_version_fails_409(self, db_session: Session):
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=True)

        response = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("guide.txt", b"Content text", "text/plain")},
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        assert "immutable" in response.json()["detail"].lower()

    def test_cross_tenant_isolation_rejected(self, db_session: Session):
        client = TestClient(app)
        # Create Org A
        user_a, org_a, token_a = _create_user_and_org(db_session, email="org_a@example.com", org_name="Org A")
        kit_a, ver_a = _create_brand_kit_and_version(db_session, org_a.id, user_a.id, is_published=False)

        # Create Org B
        user_b, org_b, token_b = _create_user_and_org(db_session, email="org_b@example.com", org_name="Org B")

        # Org B attempts to upload document to Org A's brand kit/version
        response = client.post(
            f"/api/v1/organisations/{org_a.id}/brand-kits/{kit_a.id}/versions/{ver_a.id}/documents",
            headers={"Authorization": f"Bearer {token_b}"},
            files={"file": ("guide.txt", b"Hacker content", "text/plain")},
        )
        # Rejected because user B is not a member of Org A
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_list_and_get_guideline_documents(self, db_session: Session):
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        # Upload a document
        upload_resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("guide.txt", b"Brand Guidelines Content", "text/plain")},
            data={"title": "Style Guide"},
        )
        assert upload_resp.status_code == status.HTTP_201_CREATED
        doc_id = upload_resp.json()["id"]

        # List documents
        list_resp = client.get(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert list_resp.status_code == status.HTTP_200_OK
        docs = list_resp.json()
        assert len(docs) == 1
        assert docs[0]["id"] == doc_id
        assert docs[0]["chunks_count"] >= 1

        # Get single document
        get_resp = client.get(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents/{doc_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert get_resp.status_code == status.HTTP_200_OK
        assert get_resp.json()["id"] == doc_id

        # List chunks
        chunks_resp = client.get(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents/{doc_id}/chunks",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert chunks_resp.status_code == status.HTTP_200_OK
        chunks = chunks_resp.json()
        assert len(chunks) >= 1
        assert chunks[0]["chunk_index"] == 0

        # Clean up
        doc = db_session.get(BrandGuidelineDocument, uuid.UUID(doc_id))
        if doc:
            p = doc_service.LOCAL_UPLOAD_ROOT / doc.storage_path
            if p.is_file():
                p.unlink()

    def test_delete_guideline_document_and_chunks(self, db_session: Session):
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        # Upload a document
        upload_resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("guide_to_delete.txt", b"Temporary guideline text", "text/plain")},
        )
        assert upload_resp.status_code == status.HTTP_201_CREATED
        doc_id = upload_resp.json()["id"]

        # Confirm chunks exist
        chunks_before = db_session.execute(
            select(BrandDocumentChunk).where(BrandDocumentChunk.document_id == uuid.UUID(doc_id))
        ).scalars().all()
        assert len(chunks_before) >= 1

        # Delete document
        del_resp = client.delete(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents/{doc_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert del_resp.status_code == status.HTTP_204_NO_CONTENT

        # Confirm document is deleted from DB
        doc_after = db_session.get(BrandGuidelineDocument, uuid.UUID(doc_id))
        assert doc_after is None

        # Confirm chunks are cascade-deleted
        chunks_after = db_session.execute(
            select(BrandDocumentChunk).where(BrandDocumentChunk.document_id == uuid.UUID(doc_id))
        ).scalars().all()
        assert len(chunks_after) == 0

    def test_reparse_guideline_document(self, db_session: Session):
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        upload_resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("guide.txt", b"Initial guideline text for reparsing test.", "text/plain")},
        )
        assert upload_resp.status_code == status.HTTP_201_CREATED
        doc_id = upload_resp.json()["id"]

        reparse_resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents/{doc_id}/reparse",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert reparse_resp.status_code == status.HTTP_200_OK
        data = reparse_resp.json()
        assert data["parse_attempt_count"] == 2
        assert data["parsing_status"] == DocumentParsingStatus.PARSED

        # Clean up
        doc = db_session.get(BrandGuidelineDocument, uuid.UUID(doc_id))
        if doc:
            p = doc_service.LOCAL_UPLOAD_ROOT / doc.storage_path
            if p.is_file():
                p.unlink()

    def test_upload_exceeding_10mb_fails_413(self, db_session: Session):
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        # 10MB + 1 byte payload
        oversized = b"A" * (10 * 1024 * 1024 + 1)
        response = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("large_policy.txt", oversized, "text/plain")},
        )
        assert response.status_code == status.HTTP_413_CONTENT_TOO_LARGE
        assert "exceeds maximum allowed size" in response.json()["detail"]

    def test_cross_brand_kit_version_isolation_fails_404(self, db_session: Session):
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit_a, ver_a = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)
        kit_b, ver_b = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        # Mismatched kit_a with ver_b must fail with 404
        response = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit_a.id}/versions/{ver_b.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("guide.txt", b"Mismatched kit and version", "text/plain")},
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_preserves_shared_file_if_referenced_elsewhere(self, db_session: Session):
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, ver_1 = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        upload_resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{ver_1.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("shared_guide.txt", b"Shared brand policy content across versions.", "text/plain")},
        )
        assert upload_resp.status_code == status.HTTP_201_CREATED
        doc_1_id = uuid.UUID(upload_resp.json()["id"])
        doc_1 = db_session.get(BrandGuidelineDocument, doc_1_id)
        storage_path = doc_1.storage_path
        disk_path = doc_service.LOCAL_UPLOAD_ROOT / storage_path
        assert disk_path.is_file()

        # Simulate cloned document in another version referencing the same storage_path
        doc_2 = BrandGuidelineDocument(
            id=uuid.uuid4(),
            brand_kit_version_id=ver_1.id,
            organisation_id=org.id,
            title="Shared Guide Clone",
            document_category=GuidelineDocumentCategory.STYLE_GUIDE,
            original_filename="shared_guide.txt",
            stored_filename=doc_1.stored_filename,
            storage_backend="LOCAL",
            storage_path=storage_path,
            mime_type="text/plain",
            file_size_bytes=doc_1.file_size_bytes,
            file_sha256=doc_1.file_sha256,
            parsing_status=DocumentParsingStatus.PARSED,
            parse_attempt_count=1,
            raw_text_content=doc_1.raw_text_content,
        )
        db_session.add(doc_2)
        db_session.commit()

        # Delete doc_1
        del_resp = client.delete(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{ver_1.id}/documents/{doc_1_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert del_resp.status_code == status.HTTP_204_NO_CONTENT

        # Confirm on-disk file was PRESERVED because doc_2 still references it!
        assert disk_path.is_file()

        # Clean up
        db_session.delete(doc_2)
        db_session.commit()
        if disk_path.is_file():
            disk_path.unlink()

    def test_category_validation_valid_and_invalid(self, db_session: Session):
        """CR-61-02: Test valid and invalid document categories."""
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        # 1. Invalid category rejected with 400
        res_invalid = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("guide.txt", b"Brand policy text", "text/plain")},
            data={"document_category": "INVALID_RANDOM_CATEGORY"},
        )
        assert res_invalid.status_code == status.HTTP_400_BAD_REQUEST
        assert "Invalid document category" in res_invalid.json()["detail"]

        # 2. Valid categories accepted (e.g. LEGAL_POLICY, BRAND_BOOK)
        res_valid = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("legal.txt", b"Legal terms and compliance conditions.", "text/plain")},
            data={"document_category": GuidelineDocumentCategory.LEGAL_POLICY},
        )
        assert res_valid.status_code == status.HTTP_201_CREATED
        assert res_valid.json()["document_category"] == GuidelineDocumentCategory.LEGAL_POLICY

        # Clean up
        doc = db_session.get(BrandGuidelineDocument, uuid.UUID(res_valid.json()["id"]))
        if doc:
            p = doc_service.LOCAL_UPLOAD_ROOT / doc.storage_path
            if p.is_file():
                p.unlink()

    def test_database_failure_cleanup_after_upload(self, db_session: Session, monkeypatch):
        """SEC-06: Database or chunking error after upload unlinks on-disk file."""
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        tracked_files_before = set(doc_service.LOCAL_UPLOAD_ROOT.glob(f"{org.id}/*"))

        # Simulate unexpected crash in chunking_service
        def _mock_crash(*args, **kwargs):
            raise RuntimeError("Simulated Database / Chunking Crash")

        monkeypatch.setattr(chunking_service, "chunk_document_text", _mock_crash)

        try:
            client.post(
                f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
                headers={"Authorization": f"Bearer {token}"},
                files={"file": ("fail_clean.txt", b"Text content destined to fail chunking", "text/plain")},
            )
        except RuntimeError:
            pass

        # Verify no orphan file was left in the organisation upload directory
        tracked_files_after = set(doc_service.LOCAL_UPLOAD_ROOT.glob(f"{org.id}/*"))
        assert tracked_files_after == tracked_files_before

    def test_invalid_pdf_magic_bytes_rejected_415(self, db_session: Session):
        """Upload named .pdf with invalid/corrupt header is rejected with 415."""
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("spoofed.pdf", b"NOT_A_PDF_MAGIC_BYTES_HEADER", "application/pdf")},
        )
        assert resp.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE

    def test_mime_signature_mismatch_rejected_415(self, db_session: Session):
        """Upload named .docx with invalid zip header is rejected with 415."""
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("corrupt.docx", b"NOT_A_VALID_ZIP_ARCHIVE", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
        assert resp.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE

    def test_reparse_against_published_version_fails_409(self, db_session: Session):
        """Reparsing on a published version is rejected with 409 Conflict."""
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        upload_resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("immutable_guide.txt", b"Brand guidelines to publish", "text/plain")},
        )
        assert upload_resp.status_code == status.HTTP_201_CREATED
        doc_id = upload_resp.json()["id"]

        # Publish the version in the database
        version.status = BrandKitVersionStatus.PUBLISHED
        db_session.commit()

        # Attempt reparse on published version
        reparse_resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents/{doc_id}/reparse",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert reparse_resp.status_code == status.HTTP_409_CONFLICT
        assert "immutable" in reparse_resp.json()["detail"].lower()

        # Clean up
        doc = db_session.get(BrandGuidelineDocument, uuid.UUID(doc_id))
        if doc:
            p = doc_service.LOCAL_UPLOAD_ROOT / doc.storage_path
            if p.is_file():
                p.unlink()

    def test_missing_stored_file_during_reparse_fails_404_and_sets_failed(self, db_session: Session):
        """Reparsing when on-disk binary was deleted marks document FAILED and returns 404."""
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        upload_resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("missing_guide.txt", b"Binary about to be removed", "text/plain")},
        )
        assert upload_resp.status_code == status.HTTP_201_CREATED
        doc_id = upload_resp.json()["id"]

        # Manually delete the physical file
        doc = db_session.get(BrandGuidelineDocument, uuid.UUID(doc_id))
        disk_file = (doc_service.LOCAL_UPLOAD_ROOT / doc.storage_path).resolve()
        if disk_file.is_file():
            disk_file.unlink()

        # Attempt reparse
        reparse_resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents/{doc_id}/reparse",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert reparse_resp.status_code == status.HTTP_404_NOT_FOUND

        db_session.refresh(doc)
        assert doc.parsing_status == DocumentParsingStatus.FAILED
        assert doc.last_error_code == "FILE_NOT_FOUND"

    def test_synthetic_pdf_guideline_upload_success(self, db_session: Session):
        """Verify upload and sentence-aware chunking of multi-page synthetic PDF across page boundaries."""
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        # Generate sufficient sentence-based content on each page to exceed the 512-token chunk target
        page1_sentences = [
            f"Brand Rule 1.{i}: Inkloom AI enforces strict compliance and governance across financial communication channels."
            for i in range(1, 45)
        ]
        page2_sentences = [
            f"Brand Rule 2.{i}: All marketing claims must be backed by documented evidence and approved guideline citations."
            for i in range(1, 45)
        ]

        pdf_content = _generate_synthetic_pdf([
            " ".join(page1_sentences),
            " ".join(page2_sentences),
        ])

        resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("brand_guide.pdf", pdf_content, "application/pdf")},
            data={"title": "Official Brand PDF", "document_category": GuidelineDocumentCategory.STYLE_GUIDE},
        )
        assert resp.status_code == status.HTTP_201_CREATED, resp.text
        data = resp.json()
        assert data["page_count"] == 2
        assert data["chunks_count"] >= 2

        doc_id = uuid.UUID(data["id"])
        doc = db_session.get(BrandGuidelineDocument, doc_id)
        assert doc is not None

        chunks = db_session.execute(
            select(BrandDocumentChunk)
            .where(BrandDocumentChunk.document_id == doc_id)
            .order_by(BrandDocumentChunk.chunk_index)
        ).scalars().all()
        assert len(chunks) >= 2

        # Page attribution must cover both page 1 and page 2
        pages = {c.page_number for c in chunks}
        assert 1 in pages
        assert 2 in pages

        # Assert character offsets, content integrity, and SHA-256 hashes
        for c in chunks:
            assert c.char_start >= 0
            assert c.char_end > c.char_start
            assert c.token_count > 0
            assert len(c.content_sha256) == 64
            # Content matches raw text slice exactly
            assert c.content == doc.raw_text_content[c.char_start:c.char_end]
            # SHA-256 matches chunk content exactly
            assert c.content_sha256 == hashlib.sha256(c.content.encode("utf-8")).hexdigest()

        # Verify sliding-window overlap between consecutive chunks
        for i in range(len(chunks) - 1):
            assert chunks[i + 1].char_start < chunks[i].char_end

        # Clean up
        if doc:
            p = doc_service.LOCAL_UPLOAD_ROOT / doc.storage_path
            if p.is_file():
                p.unlink()

    def test_synthetic_docx_guideline_upload_success(self, db_session: Session):
        """Verify upload and sentence-aware chunking of synthetic DOCX document."""
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        docx_content = _generate_synthetic_docx([
            "Inkloom AI Brand Tone Playbook 2026.",
            "Our voice is authoritative, transparent, and educational.",
            "Always avoid sensationalist superlatives like 'unmatched' or 'guaranteed'.",
        ])

        resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("playbook.docx", docx_content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"title": "Tone Playbook", "document_category": GuidelineDocumentCategory.TONE_PLAYBOOK},
        )
        assert resp.status_code == status.HTTP_201_CREATED
        data = resp.json()
        assert data["document_category"] == GuidelineDocumentCategory.TONE_PLAYBOOK
        assert data["chunks_count"] >= 1

        # Clean up
        doc = db_session.get(BrandGuidelineDocument, uuid.UUID(data["id"]))
        if doc:
            p = doc_service.LOCAL_UPLOAD_ROOT / doc.storage_path
            if p.is_file():
                p.unlink()

    def test_failed_reparse_preserves_previously_existing_chunks(self, db_session: Session, monkeypatch):
        """CR-61-01: Verify failed reparse rolls back and preserves existing chunks."""
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version = _create_brand_kit_and_version(db_session, org.id, user.id, is_published=False)

        upload_resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents",
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("reparse_safe.txt", b"Valid brand policy text before crash.", "text/plain")},
        )
        assert upload_resp.status_code == status.HTTP_201_CREATED
        doc_id = uuid.UUID(upload_resp.json()["id"])

        chunks_before = db_session.execute(
            select(BrandDocumentChunk).where(BrandDocumentChunk.document_id == doc_id)
        ).scalars().all()
        assert len(chunks_before) >= 1
        original_chunk_ids = {c.id for c in chunks_before}

        # Simulate failure in chunking_service during reparse (after chunks were queued for deletion)
        def _mock_rechunk_crash(*args, **kwargs):
            raise RuntimeError("Simulated Re-chunking Failure during reparse")

        monkeypatch.setattr(chunking_service, "chunk_document_text", _mock_rechunk_crash)

        reparse_resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents/{doc_id}/reparse",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert reparse_resp.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "Reparsing failed" in reparse_resp.json()["detail"]

        # Confirm document is marked FAILED
        doc = db_session.get(BrandGuidelineDocument, doc_id)
        assert doc.parsing_status == DocumentParsingStatus.FAILED
        assert doc.last_error_code == "EXTRACTION_FAILED"

        # CRITICAL ASSERTION: The original chunks were NOT deleted!
        chunks_after = db_session.execute(
            select(BrandDocumentChunk).where(BrandDocumentChunk.document_id == doc_id)
        ).scalars().all()
        assert len(chunks_after) == len(chunks_before)
        assert {c.id for c in chunks_after} == original_chunk_ids

        # Clean up
        if doc:
            p = doc_service.LOCAL_UPLOAD_ROOT / doc.storage_path
            if p.is_file():
                p.unlink()



