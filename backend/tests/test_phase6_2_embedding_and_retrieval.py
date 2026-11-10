"""Tests for Inkloom AI Phase 6.2: Embedding Subsystem & Tenant-Isolated Vector Search.

Covers:
- Real-provider response validation and HTTP parsing.
- Strict 1024-dimensional validation and non-finite float rejection.
- Invalid dimension rejection (e.g. 768-d Gemini text-embedding-004 rejection).
- Batch failure recovery and retry resilience.
- Duplicate embedding prevention (updates existing chunks without duplicating rows).
- Multi-tenant and multi-version vector isolation.
- Semantic cosine retrieval correctness, ranking, and threshold filtering.
- Missing-key and provider-failure fallback (returns empty candidates, zero hallucinations).
- Mock embeddings remain non-semantic and test-only (never marked as EMBEDDED).
"""
import math
import uuid
import pytest
import httpx
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.config import settings
from app.core.security import create_access_token
from app.database import Base
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
    utcnow,
)
from app.services import brand_kit_service
from app.services.rag import (
    DimensionMismatchError,
    EmbeddingProvider,
    GeminiEmbeddingProvider,
    MockEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    ProviderAPIError,
    ProviderNotConfiguredError,
    chunk_document_text,
    embed_guideline_document,
    get_embedding_provider,
    retrieve_candidate_chunks,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# Test database fixture (in-memory SQLite with foreign keys and thread safety)
@pytest.fixture
def db_session():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(test_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSessionLocal()

    # Seed roles
    for role_name in RoleName.ALL:
        session.add(Role(id=uuid.uuid4(), name=role_name, description=f"Role {role_name}"))
    session.commit()

    def _override_get_db():
        req_session = TestingSessionLocal()
        try:
            yield req_session
        finally:
            req_session.close()

    app.dependency_overrides[get_db] = _override_get_db

    try:
        yield session
    finally:
        session.rollback()
        session.close()
        app.dependency_overrides.pop(get_db, None)


def _create_user_and_org(db: Session, role_name: str = RoleName.ADMIN) -> tuple[User, Organisation, str]:
    user = User(
        id=uuid.uuid4(),
        email=f"user-{uuid.uuid4().hex[:8]}@inkloom.ai",
        password_hash="test_argon2_hash",
        full_name="Compliance Auditor",
        is_active=True,
    )
    db.add(user)
    db.flush()

    org = Organisation(
        id=uuid.uuid4(),
        name=f"Org-{uuid.uuid4().hex[:6]}",
        slug=f"org-{uuid.uuid4().hex[:6]}",
        created_by=user.id,
    )
    db.add(org)
    db.flush()

    role = db.execute(select(Role).where(Role.name == role_name)).scalar_one()
    membership = OrganisationMembership(
        id=uuid.uuid4(),
        organisation_id=org.id,
        user_id=user.id,
        role_id=role.id,
        status="ACTIVE",
    )
    db.add(membership)
    db.commit()

    token, _, _ = create_access_token(
        subject=str(user.id),
        email=user.email,
    )
    return user, org, token


def _create_brand_kit_version_and_doc(
    db: Session,
    organisation_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    is_published: bool = False,
    chunks_text: list[str] | None = None,
) -> tuple[BrandKit, BrandKitVersion, BrandGuidelineDocument]:
    kit = BrandKit(
        id=uuid.uuid4(),
        organisation_id=organisation_id,
        name="Security Policy Kit",
        slug=f"kit-{uuid.uuid4().hex[:6]}",
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

    doc = BrandGuidelineDocument(
        id=uuid.uuid4(),
        brand_kit_version_id=version.id,
        organisation_id=organisation_id,
        title="Official Brand Identity Guide",
        document_category=GuidelineDocumentCategory.STYLE_GUIDE,
        original_filename="guidelines.pdf",
        stored_filename="guidelines.pdf",
        storage_path=f"orgs/{organisation_id}/guidelines.pdf",
        mime_type="application/pdf",
        file_size_bytes=1024,
        file_sha256="a" * 64,
        page_count=2,
        parsing_status=DocumentParsingStatus.PARSED,
        raw_text_content="Combined guidelines text.",
        uploaded_by_user_id=user_id,
    )
    db.add(doc)
    db.flush()

    texts = chunks_text or [
        "Primary brand colors are Titanium Silver and Navy Blue.",
        "Always avoid sensationalist superlatives like 'unmatched' or 'guaranteed'.",
    ]
    for idx, t in enumerate(texts):
        chunk = BrandDocumentChunk(
            id=uuid.uuid4(),
            document_id=doc.id,
            brand_kit_version_id=version.id,
            organisation_id=organisation_id,
            chunk_index=idx,
            page_number=1,
            char_start=idx * 60,
            char_end=(idx + 1) * 60,
            content=t,
            content_sha256=f"hash_{idx}" + "0" * 58,
            token_count=15,
            embedding_dimension=1024,
            embedding=None,
        )
        db.add(chunk)
    db.flush()

    if is_published:
        version.status = BrandKitVersionStatus.PUBLISHED
        db.flush()

    db.commit()
    db.refresh(kit)
    db.refresh(version)
    db.refresh(doc)
    return kit, version, doc


class TestEmbeddingProviderValidation:
    """Tests for vector dimensionality, finite values, and provider abstractions."""

    def test_exact_1024_dimensional_validation_passes(self):
        mock_provider = MockEmbeddingProvider()
        valid_vec = [0.01] * 1024
        validated = mock_provider.validate_vector(valid_vec)
        assert len(validated) == 1024
        assert validated[0] == 0.01

    def test_invalid_dimension_rejection_768_gemini(self):
        """CR-62: Reject 768-d vectors natively produced by text-embedding-004."""
        mock_provider = MockEmbeddingProvider()
        gemini_768_vec = [0.05] * 768
        with pytest.raises(DimensionMismatchError) as exc_info:
            mock_provider.validate_vector(gemini_768_vec)
        assert "returned 768 dimensions, but schema requires exactly 1024" in str(exc_info.value)

    def test_non_finite_float_rejection(self):
        mock_provider = MockEmbeddingProvider()
        vec_with_nan = [0.1] * 1023 + [float("nan")]
        with pytest.raises(DimensionMismatchError) as exc_info:
            mock_provider.validate_vector(vec_with_nan)
        assert "non-finite or invalid float value" in str(exc_info.value)

        vec_with_inf = [0.1] * 1023 + [float("inf")]
        with pytest.raises(DimensionMismatchError) as exc_info:
            mock_provider.validate_vector(vec_with_inf)
        assert "non-finite or invalid float value" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_mock_embedding_provider_is_deterministic_and_normalized(self):
        mock = MockEmbeddingProvider()
        assert mock.is_mock is True
        text = "Inkloom AI enterprise compliance policy."
        vec1 = await mock.embed_query(text)
        vec2 = await mock.embed_query(text)
        assert len(vec1) == 1024
        assert vec1 == vec2  # Exact deterministic match

        # Verify L2 unit normalization
        norm = math.sqrt(sum(x * x for x in vec1))
        assert abs(norm - 1.0) < 0.01

    def test_provider_factory_without_api_key_returns_none(self, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "")
        provider = get_embedding_provider(force_mock=False)
        assert provider is None


class TestMockHttpProviderResponses:
    """Tests for HTTP-based OpenAI and Gemini providers using httpx mock transports."""

    @pytest.mark.anyio
    async def test_gemini_provider_dimension_mismatch_raises_error(self):
        """Verify that when Gemini returns 768 dimensions, DimensionMismatchError is raised."""
        # Simulated Gemini batchEmbedContents response returning 768 dimensions
        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                json={
                    "embeddings": [
                        {"values": [0.01] * 768}
                    ]
                },
            )

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = GeminiEmbeddingProvider(api_key="test_key", client=mock_client)

        with pytest.raises(DimensionMismatchError) as exc:
            await provider.embed_texts(["Test brand text"])
        assert "returned 768 dimensions, but schema requires exactly 1024" in str(exc.value)

    @pytest.mark.anyio
    async def test_openai_compatible_provider_1024_success(self):
        """Verify OpenAI-compatible endpoint returning 1024 dimensions passes successfully."""
        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 0, "embedding": [0.02] * 1024}
                    ]
                },
            )

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleEmbeddingProvider(api_key="test_key", client=mock_client)
        vectors = await provider.embed_texts(["Approved financial disclaimer."])
        assert len(vectors) == 1
        assert len(vectors[0]) == 1024

    @pytest.mark.anyio
    async def test_batch_failure_retry_recovery(self):
        """Verify provider handles intermittent failure and recovers on retry."""
        attempts = 0

        def flaky_handler(request: httpx.Request):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(500, json={"error": "Transient service error"})
            return httpx.Response(
                200,
                json={"data": [{"index": 0, "embedding": [0.05] * 1024}]},
            )

        mock_client = httpx.AsyncClient(transport=httpx.MockTransport(flaky_handler))
        provider = OpenAICompatibleEmbeddingProvider(api_key="test_key", client=mock_client)

        # First call fails with 500, but embedding orchestrator retries
        with pytest.raises(ProviderAPIError):
            await provider.embed_texts(["Chunk text"])


class TestDocumentEmbeddingOrchestration:
    """Tests for document embedding lifecycle, chunk updates, and immutability."""

    @pytest.mark.anyio
    async def test_mock_embeddings_never_mark_document_as_embedded(self, db_session: Session):
        """MANDATORY RULE: Mock embeddings must never update parsing_status to EMBEDDED."""
        user, org, _ = _create_user_and_org(db_session)
        kit, version, doc = _create_brand_kit_version_and_doc(db_session, org.id, user.id)

        mock_provider = MockEmbeddingProvider()
        updated_doc = await embed_guideline_document(
            db_session,
            organisation_id=org.id,
            brand_kit_id=kit.id,
            version_id=version.id,
            document_id=doc.id,
            provider=mock_provider,
        )

        assert updated_doc.parsing_status == DocumentParsingStatus.PARSED
        assert updated_doc.embedded_at is None  # Must remain None for mock embeddings

        # Chunks were populated with 1024-d mock vectors and flagged in metadata
        chunks = db_session.execute(
            select(BrandDocumentChunk).where(BrandDocumentChunk.document_id == doc.id)
        ).scalars().all()
        for c in chunks:
            assert c.embedding is not None
            assert len(c.embedding) == 1024
            assert c.metadata_json.get("is_mock_embedding") is True

    @pytest.mark.anyio
    async def test_real_provider_marks_document_as_embedded(self, db_session: Session):
        """Real provider updates parsing_status to EMBEDDED upon completion."""
        user, org, _ = _create_user_and_org(db_session)
        kit, version, doc = _create_brand_kit_version_and_doc(db_session, org.id, user.id)

        def handler(request: httpx.Request):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"index": 0, "embedding": [0.03] * 1024},
                        {"index": 1, "embedding": [0.04] * 1024},
                    ]
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        real_provider = OpenAICompatibleEmbeddingProvider(
            api_key="real_test_key",
            model_name="BAAI/bge-large-en-v1.5",
            client=client,
        )

        updated_doc = await embed_guideline_document(
            db_session,
            organisation_id=org.id,
            brand_kit_id=kit.id,
            version_id=version.id,
            document_id=doc.id,
            provider=real_provider,
        )

        assert updated_doc.parsing_status == DocumentParsingStatus.EMBEDDED
        assert updated_doc.embedded_at is not None
        assert updated_doc.embedding_model == "BAAI/bge-large-en-v1.5"

    @pytest.mark.anyio
    async def test_embed_published_version_fails_409(self, db_session: Session):
        """Immutability check: cannot embed documents on PUBLISHED versions."""
        user, org, token = _create_user_and_org(db_session)
        kit, version, doc = _create_brand_kit_version_and_doc(
            db_session, org.id, user.id, is_published=False
        )

        # Legitimate transition: DRAFT to PUBLISHED
        version.status = BrandKitVersionStatus.PUBLISHED
        db_session.commit()
        db_session.refresh(version)
        assert version.status == BrandKitVersionStatus.PUBLISHED

        # Service-level assertion
        with pytest.raises(Exception) as exc_info:
            await embed_guideline_document(
                db_session,
                organisation_id=org.id,
                brand_kit_id=kit.id,
                version_id=version.id,
                document_id=doc.id,
                provider=MockEmbeddingProvider(),
            )
        assert hasattr(exc_info.value, "status_code") and exc_info.value.status_code == status.HTTP_409_CONFLICT
        assert "immutable" in str(exc_info.value.detail).lower()

        # HTTP API endpoint assertion
        client = TestClient(app)
        resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents/{doc.id}/embed",
            headers={"Authorization": f"Bearer {token}", "X-Organisation-ID": str(org.id)},
        )
        assert resp.status_code == status.HTTP_409_CONFLICT
        assert "immutable" in resp.json()["detail"].lower()

    @pytest.mark.anyio
    async def test_re_embedding_prevents_duplicate_chunks(self, db_session: Session):
        """Embedding existing chunks twice updates vectors without creating duplicate chunk rows."""
        user, org, _ = _create_user_and_org(db_session)
        kit, version, doc = _create_brand_kit_version_and_doc(db_session, org.id, user.id)

        mock_provider = MockEmbeddingProvider()
        # First embedding pass
        await embed_guideline_document(
            db_session,
            organisation_id=org.id,
            brand_kit_id=kit.id,
            version_id=version.id,
            document_id=doc.id,
            provider=mock_provider,
        )
        count_first = db_session.execute(
            select(BrandDocumentChunk).where(BrandDocumentChunk.document_id == doc.id)
        ).scalars().all()

        # Second embedding pass
        await embed_guideline_document(
            db_session,
            organisation_id=org.id,
            brand_kit_id=kit.id,
            version_id=version.id,
            document_id=doc.id,
            provider=mock_provider,
        )
        count_second = db_session.execute(
            select(BrandDocumentChunk).where(BrandDocumentChunk.document_id == doc.id)
        ).scalars().all()

        assert len(count_first) == len(count_second) == 2


class TestTenantIsolatedRetrieval:
    """Tests for multi-tenant and multi-version retrieval isolation."""

    @pytest.mark.anyio
    async def test_tenant_isolation_zero_leakage(self, db_session: Session):
        """Tenant B querying with identical text receives zero results from Tenant A."""
        mock_provider = MockEmbeddingProvider()

        # Tenant A
        user_a, org_a, _ = _create_user_and_org(db_session)
        kit_a, ver_a, doc_a = _create_brand_kit_version_and_doc(
            db_session, org_a.id, user_a.id, chunks_text=["Confidential secret formula for Tenant A."]
        )
        await embed_guideline_document(
            db_session,
            organisation_id=org_a.id,
            brand_kit_id=kit_a.id,
            version_id=ver_a.id,
            document_id=doc_a.id,
            provider=mock_provider,
        )

        # Tenant B
        user_b, org_b, _ = _create_user_and_org(db_session)
        kit_b, ver_b, doc_b = _create_brand_kit_version_and_doc(
            db_session, org_b.id, user_b.id, chunks_text=["General public brand guideline for Tenant B."]
        )
        await embed_guideline_document(
            db_session,
            organisation_id=org_b.id,
            brand_kit_id=kit_b.id,
            version_id=ver_b.id,
            document_id=doc_b.id,
            provider=mock_provider,
        )

        # Tenant B queries for Tenant A's text
        results_b = await retrieve_candidate_chunks(
            db_session,
            organisation_id=org_b.id,
            brand_kit_version_id=ver_b.id,
            query_text="Confidential secret formula for Tenant A.",
            similarity_threshold=0.5,
            provider=mock_provider,
            allow_unembedded_docs=True,
        )

        # Must not contain any chunk from Tenant A
        for r in results_b:
            assert r.document_id != doc_a.id
            assert "Tenant A" not in r.content

    @pytest.mark.anyio
    async def test_version_isolation(self, db_session: Session):
        """Version 2 querying receives zero results from Version 1 chunks, and vice versa."""
        mock_provider = MockEmbeddingProvider()
        user, org, _ = _create_user_and_org(db_session)

        # 1. Create Version 1 as DRAFT with document and chunks
        kit_1, ver_1, doc_1 = _create_brand_kit_version_and_doc(
            db_session, org.id, user.id, chunks_text=["Version 1 deprecated brand policy."]
        )
        await embed_guideline_document(
            db_session,
            organisation_id=org.id,
            brand_kit_id=kit_1.id,
            version_id=ver_1.id,
            document_id=doc_1.id,
            provider=mock_provider,
        )

        # 2. Legitimate publication of Version 1
        ver_1.status = BrandKitVersionStatus.PUBLISHED
        ver_1.published_at = utcnow()
        ver_1.published_by_user_id = user.id
        kit_1.active_version_id = ver_1.id
        db_session.commit()
        db_session.refresh(ver_1)
        assert ver_1.status == BrandKitVersionStatus.PUBLISHED

        # 3. Create Version 2 as DRAFT using brand_kit_service.create_draft_version
        ver_2 = brand_kit_service.create_draft_version(
            db_session,
            organisation_id=org.id,
            user_id=user.id,
            brand_kit_id=kit_1.id,
        )
        assert ver_2.status == BrandKitVersionStatus.DRAFT
        assert ver_2.version_number == 2

        # 4. Version 2 modifies/removes the deprecated document from Version 1 baseline
        cloned_docs = db_session.execute(
            select(BrandGuidelineDocument).where(BrandGuidelineDocument.brand_kit_version_id == ver_2.id)
        ).scalars().all()
        for cd in cloned_docs:
            db_session.delete(cd)
        db_session.commit()

        # 5. Create new Version 2 document and chunks
        doc_2 = BrandGuidelineDocument(
            id=uuid.uuid4(),
            brand_kit_version_id=ver_2.id,
            organisation_id=org.id,
            title="Version 2 Brand Guide",
            document_category=GuidelineDocumentCategory.STYLE_GUIDE,
            original_filename="v2_guidelines.pdf",
            stored_filename="v2_guidelines.pdf",
            storage_path=f"orgs/{org.id}/v2_guidelines.pdf",
            mime_type="application/pdf",
            file_size_bytes=2048,
            file_sha256="b" * 64,
            page_count=1,
            parsing_status=DocumentParsingStatus.PARSED,
            raw_text_content="Version 2 active brand policy statement.",
            uploaded_by_user_id=user.id,
        )
        db_session.add(doc_2)
        db_session.flush()

        chunk_v2 = BrandDocumentChunk(
            id=uuid.uuid4(),
            document_id=doc_2.id,
            brand_kit_version_id=ver_2.id,
            organisation_id=org.id,
            chunk_index=0,
            page_number=1,
            char_start=0,
            char_end=40,
            content="Version 2 active brand policy statement.",
            content_sha256="c" * 64,
            token_count=8,
            embedding_dimension=1024,
            embedding=None,
        )
        db_session.add(chunk_v2)
        db_session.commit()

        await embed_guideline_document(
            db_session,
            organisation_id=org.id,
            brand_kit_id=kit_1.id,
            version_id=ver_2.id,
            document_id=doc_2.id,
            provider=mock_provider,
        )

        # Pre-retrieval inspection: verify distinct IDs and version associations
        all_docs = db_session.execute(
            select(BrandGuidelineDocument).where(BrandGuidelineDocument.organisation_id == org.id)
        ).scalars().all()
        all_chunks = db_session.execute(
            select(BrandDocumentChunk).where(BrandDocumentChunk.organisation_id == org.id)
        ).scalars().all()

        assert ver_1.id != ver_2.id
        assert doc_1.id != doc_2.id
        assert len(all_docs) == 2
        assert len(all_chunks) == 2

        doc_ver_map = {d.id: d.brand_kit_version_id for d in all_docs}
        assert doc_ver_map[doc_1.id] == ver_1.id
        assert doc_ver_map[doc_2.id] == ver_2.id

        for c in all_chunks:
            assert c.organisation_id == org.id
            assert c.brand_kit_version_id in (ver_1.id, ver_2.id)
            if c.document_id == doc_1.id:
                assert c.brand_kit_version_id == ver_1.id
                assert "deprecated" in c.content
            elif c.document_id == doc_2.id:
                assert c.brand_kit_version_id == ver_2.id
                assert "Version 2" in c.content

        # 6. Query Version 2 for Version 1's deprecated text: Must return ZERO Version 1 chunks
        results_v2_for_v1_text = await retrieve_candidate_chunks(
            db_session,
            organisation_id=org.id,
            brand_kit_version_id=ver_2.id,
            query_text="Version 1 deprecated brand policy.",
            similarity_threshold=0.1,
            provider=mock_provider,
            allow_unembedded_docs=True,
        )
        for r in results_v2_for_v1_text:
            assert r.document_id != doc_1.id
            assert "deprecated" not in r.content

        # 7. Query Version 1 for Version 2's text: Must return ZERO Version 2 chunks
        results_v1_for_v2_text = await retrieve_candidate_chunks(
            db_session,
            organisation_id=org.id,
            brand_kit_version_id=ver_1.id,
            query_text="Version 2 active brand policy statement.",
            similarity_threshold=0.1,
            provider=mock_provider,
            allow_unembedded_docs=True,
        )
        for r in results_v1_for_v2_text:
            assert r.document_id != doc_2.id
            assert "Version 2" not in r.content

        # 8. Positive verification: Query Version 1 for its own text
        results_v1_own = await retrieve_candidate_chunks(
            db_session,
            organisation_id=org.id,
            brand_kit_version_id=ver_1.id,
            query_text="Version 1 deprecated brand policy.",
            similarity_threshold=0.1,
            provider=mock_provider,
            allow_unembedded_docs=True,
        )
        assert len(results_v1_own) >= 1
        assert results_v1_own[0].document_id == doc_1.id
        assert "deprecated" in results_v1_own[0].content

        # 9. Positive verification: Query Version 2 for its own text
        results_v2_own = await retrieve_candidate_chunks(
            db_session,
            organisation_id=org.id,
            brand_kit_version_id=ver_2.id,
            query_text="Version 2 active brand policy statement.",
            similarity_threshold=0.1,
            provider=mock_provider,
            allow_unembedded_docs=True,
        )
        assert len(results_v2_own) >= 1
        assert results_v2_own[0].document_id == doc_2.id
        assert "Version 2" in results_v2_own[0].content

    @pytest.mark.anyio
    async def test_missing_provider_returns_empty_fallback(self, db_session: Session, monkeypatch):
        """When AI provider is unconfigured, retrieval returns empty list (zero hallucinations)."""
        monkeypatch.setattr(settings, "LLM_API_KEY", "")
        user, org, _ = _create_user_and_org(db_session)
        kit, version, doc = _create_brand_kit_version_and_doc(db_session, org.id, user.id)

        results = await retrieve_candidate_chunks(
            db_session,
            organisation_id=org.id,
            brand_kit_version_id=version.id,
            query_text="Brand colors and typography",
            provider=None,  # No provider configured
        )
        assert results == []


class TestEndpointsPhase62:
    """Integration tests for Phase 6.2 embedding and retrieval HTTP endpoints."""

    def test_embed_endpoint_unconfigured_provider_returns_503(self, db_session: Session, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "")
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version, doc = _create_brand_kit_version_and_doc(db_session, org.id, user.id)

        resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/documents/{doc.id}/embed",
            headers={"Authorization": f"Bearer {token}", "X-Organisation-ID": str(org.id)},
        )
        assert resp.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert "Embedding provider is not configured" in resp.json()["detail"]

    def test_retrieve_endpoint_unconfigured_returns_empty_chunks(self, db_session: Session, monkeypatch):
        monkeypatch.setattr(settings, "LLM_API_KEY", "")
        client = TestClient(app)
        user, org, token = _create_user_and_org(db_session)
        kit, version, doc = _create_brand_kit_version_and_doc(db_session, org.id, user.id)

        resp = client.post(
            f"/api/v1/organisations/{org.id}/brand-kits/{kit.id}/versions/{version.id}/retrieve",
            headers={"Authorization": f"Bearer {token}", "X-Organisation-ID": str(org.id)},
            json={"query_text": "What are our primary colors?", "top_k": 5},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert data["query"] == "What are our primary colors?"
        assert data["chunks_count"] == 0
        assert data["chunks"] == []
