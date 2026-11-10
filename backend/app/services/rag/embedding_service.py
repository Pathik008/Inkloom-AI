"""Embedding subsystem for Inkloom AI (Phase 6.2).

Provides:
- Real HTTP embedding provider abstractions (Gemini API & OpenAI-compatible).
- Strict 1024-dimension validation against pgvector schema constraints.
- Dimension mismatch detection and rejection.
- Mock embedding provider strictly isolated to offline testing.
- Bounded batch processing with retry, timeout, and semaphore controls.
- Document embedding orchestration (supporting existing PARSED chunks).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import struct
import uuid
from abc import ABC, abstractmethod
from typing import Any, List, Sequence

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.brand import (
    BrandAuditLog,
    BrandAuditResourceType,
    BrandDocumentChunk,
    BrandGuidelineDocument,
    BrandKitVersion,
    BrandKitVersionStatus,
    DocumentParsingStatus,
    utcnow,
)
from app.services import brand_kit_service

logger = logging.getLogger(__name__)

# Configuration constants
EXPECTED_EMBEDDING_DIMENSION = 1024
DEFAULT_BATCH_SIZE = 16
MAX_BATCH_SIZE = 64
HTTP_TIMEOUT_SECONDS = 15.0
MAX_EMBEDDING_RETRIES = 2

_embedding_semaphore: asyncio.Semaphore | None = None
_embedding_semaphore_loop = None


def get_embedding_semaphore() -> asyncio.Semaphore:
    """Return a shared singleton semaphore bound to the running event loop."""
    global _embedding_semaphore, _embedding_semaphore_loop
    current_loop = asyncio.get_running_loop()
    if _embedding_semaphore is None or _embedding_semaphore_loop != current_loop:
        _embedding_semaphore = asyncio.Semaphore(5)
        _embedding_semaphore_loop = current_loop
    return _embedding_semaphore


class EmbeddingError(Exception):
    """Base exception for embedding subsystem errors."""


class ProviderNotConfiguredError(EmbeddingError):
    """Raised when an embedding provider is required but no API key is configured."""


class DimensionMismatchError(EmbeddingError):
    """Raised when an embedding provider returns vectors that do not match the 1024-d schema."""


class ProviderAPIError(EmbeddingError):
    """Raised when an external embedding provider returns an HTTP error or malformed payload."""


class EmbeddingProvider(ABC):
    """Abstract interface for text embedding providers."""

    provider_name: str
    model_name: str
    expected_dimension: int = EXPECTED_EMBEDDING_DIMENSION
    is_mock: bool = False

    @abstractmethod
    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Generate normalized vector embeddings for a sequence of texts."""

    async def embed_query(self, text: str) -> list[float]:
        """Generate embedding vector for a single query text."""
        results = await self.embed_texts([text])
        if not results:
            raise ProviderAPIError("Embedding provider returned empty response for query.")
        return results[0]

    def validate_vector(self, vector: list[float], context_idx: int = 0) -> list[float]:
        """Validate vector length, dimensionality, and finite values."""
        if not isinstance(vector, (list, tuple)):
            raise DimensionMismatchError(f"Item {context_idx}: vector is not a list/tuple (got {type(vector).__name__}).")

        actual_dim = len(vector)
        if actual_dim != self.expected_dimension:
            raise DimensionMismatchError(
                f"Item {context_idx}: Provider '{self.provider_name}' model '{self.model_name}' "
                f"returned {actual_dim} dimensions, but schema requires exactly {self.expected_dimension}."
            )

        for i, val in enumerate(vector):
            if not isinstance(val, (int, float)) or not math.isfinite(val):
                raise DimensionMismatchError(
                    f"Item {context_idx}, dimension {i}: non-finite or invalid float value ({val})."
                )

        return [float(v) for v in vector]


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Google Gemini embedding provider using HTTPX.

    Supports Google's Gemini API endpoints (`v1beta/models/{model}:embedContent`
    or `v1beta/openai/embeddings`).
    Strictly verifies that the output matches 1024 dimensions.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "text-embedding-004",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key or not api_key.strip():
            raise ProviderNotConfiguredError("Gemini API key is required and cannot be empty.")
        self.api_key = api_key.strip()
        self.provider_name = "google_gemini"
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self._external_client = client

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        clean_texts = [t.strip() for t in texts]
        results: list[list[float]] = []

        # Prepare HTTP client
        client = self._external_client or httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS)
        should_close = self._external_client is None

        try:
            # Call batchEmbedContents or sequential embedContent
            # Gemini REST API: /v1beta/models/{model}:batchEmbedContents
            url = f"{self.base_url}/models/{self.model_name}:batchEmbedContents?key={self.api_key}"
            requests_payload = [
                {
                    "model": f"models/{self.model_name}",
                    "content": {"parts": [{"text": t or " "}]},
                    "outputDimensionality": self.expected_dimension,
                }
                for t in clean_texts
            ]

            payload = {"requests": requests_payload}
            response = await client.post(url, json=payload)

            if response.status_code == 404 or "not found" in response.text.lower():
                # Fallback to OpenAI-compatible endpoint if standard Gemini route 404s
                return await self._fallback_openai_compatible(clean_texts, client)

            if response.is_error:
                error_detail = response.text[:400]
                # If outputDimensionality was rejected as exceeding native 768 limit
                if "output_dimensionality" in error_detail.lower() or "dimension" in error_detail.lower():
                    raise DimensionMismatchError(
                        f"Gemini API rejected outputDimensionality={self.expected_dimension}: {error_detail}"
                    )
                raise ProviderAPIError(f"Gemini API returned status {response.status_code}: {error_detail}")

            data = response.json()
            embeddings_data = data.get("embeddings", [])
            if len(embeddings_data) != len(clean_texts):
                raise ProviderAPIError(
                    f"Expected {len(clean_texts)} embeddings, but Gemini returned {len(embeddings_data)}."
                )

            for idx, item in enumerate(embeddings_data):
                raw_vector = item.get("values", [])
                valid_vector = self.validate_vector(raw_vector, context_idx=idx)
                results.append(valid_vector)

            return results
        except httpx.RequestError as exc:
            raise ProviderAPIError(f"HTTP request to Gemini API failed: {exc}") from exc
        finally:
            if should_close:
                await client.aclose()

    async def _fallback_openai_compatible(self, texts: list[str], client: httpx.AsyncClient) -> list[list[float]]:
        """Fallback to Gemini OpenAI-compatible embeddings route."""
        url = "https://generativelanguage.googleapis.com/v1beta/openai/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model_name,
            "input": texts,
            "dimensions": self.expected_dimension,
        }
        response = await client.post(url, headers=headers, json=payload)
        if response.is_error:
            raise ProviderAPIError(f"Gemini OpenAI-compatible endpoint returned status {response.status_code}: {response.text[:300]}")

        data = response.json()
        embeddings_items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
        results = []
        for idx, item in enumerate(embeddings_items):
            vec = item.get("embedding", [])
            valid_vec = self.validate_vector(vec, context_idx=idx)
            results.append(valid_vec)
        return results


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    """Generic OpenAI-compatible embedding provider.

    Works with OpenAI API, vLLM, Ollama, or Hugging Face Text Embeddings Inference (TEI).
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "BAAI/bge-large-en-v1.5",
        base_url: str = "https://api.openai.com/v1",
        client: httpx.AsyncClient | None = None,
    ):
        if not api_key or not api_key.strip():
            raise ProviderNotConfiguredError("API key is required for OpenAI-compatible embedding provider.")
        self.api_key = api_key.strip()
        self.provider_name = "openai_compatible"
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self._external_client = client

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        clean_texts = [t.strip() for t in texts]
        client = self._external_client or httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS)
        should_close = self._external_client is None

        try:
            url = f"{self.base_url}/embeddings"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload: dict[str, Any] = {
                "model": self.model_name,
                "input": clean_texts,
            }
            # Only include dimensions param if using OpenAI v3 models that support truncation
            if "text-embedding-3" in self.model_name.lower():
                payload["dimensions"] = self.expected_dimension

            response = await client.post(url, headers=headers, json=payload)
            if response.is_error:
                raise ProviderAPIError(
                    f"OpenAI-compatible embedding endpoint returned status {response.status_code}: {response.text[:300]}"
                )

            data = response.json()
            items = sorted(data.get("data", []), key=lambda x: x.get("index", 0))
            if len(items) != len(clean_texts):
                raise ProviderAPIError(f"Expected {len(clean_texts)} embeddings, got {len(items)}.")

            results: list[list[float]] = []
            for idx, item in enumerate(items):
                vec = item.get("embedding", [])
                valid_vec = self.validate_vector(vec, context_idx=idx)
                results.append(valid_vec)

            return results
        except httpx.RequestError as exc:
            raise ProviderAPIError(f"HTTP request to embedding provider failed: {exc}") from exc
        finally:
            if should_close:
                await client.aclose()


class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic, non-semantic test-only embedding provider.

    Uses SHA-256 digests expanded deterministically into unit-normalized 1024-d float vectors.
    MANDATORY CONSTRAINT:
    `is_mock = True` is permanently hardcoded.
    Documents processed by this provider are NEVER marked as EMBEDDED in production.
    """

    def __init__(self, model_name: str = "mock-sha256-deterministic"):
        self.provider_name = "mock_sha256"
        self.model_name = model_name
        self.expected_dimension = EXPECTED_EMBEDDING_DIMENSION
        self.is_mock = True

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for idx, t in enumerate(texts):
            clean = t.strip()
            # Deterministically expand text SHA-256 into 1024 floats
            vector = self._generate_deterministic_vector(clean)
            valid_vec = self.validate_vector(vector, context_idx=idx)
            results.append(valid_vec)
        return results

    def _generate_deterministic_vector(self, text: str) -> list[float]:
        """Expand SHA-256 hash into 1024 deterministic pseudo-random floats, L2-normalized."""
        values: list[float] = []
        # Generate 1024 floats from repeated hashing with index seeds
        for i in range(1024 // 8):  # 128 iterations * 8 floats = 1024 floats
            h = hashlib.sha256(f"{text}::{i}".encode("utf-8")).digest()
            # Unpack 32 bytes as 8 32-bit signed ints
            ints = struct.unpack(">8i", h)
            for val in ints:
                # Map to float in range [-1.0, 1.0]
                values.append(val / 2147483648.0)

        # L2-normalize vector so cosine distance arithmetic behaves realistically
        norm = math.sqrt(sum(x * x for x in values)) or 1.0
        return [round(x / norm, 6) for x in values]


def get_embedding_provider(
    *,
    force_mock: bool = False,
    override_api_key: str | None = None,
) -> EmbeddingProvider | None:
    """Factory to retrieve active embedding provider based on configuration."""
    if force_mock:
        return MockEmbeddingProvider()

    api_key = (override_api_key or settings.LLM_API_KEY or "").strip()
    # Check if API key is missing or placeholder
    if not api_key or api_key in ('""', "''"):
        return None

    provider_name = settings.LLM_PROVIDER.lower().strip()
    model_name = settings.EMBEDDING_MODEL_NAME.strip()

    if "gemini" in provider_name or "google" in provider_name or "text-embedding-004" in model_name:
        return GeminiEmbeddingProvider(api_key=api_key, model_name=model_name)
    else:
        return OpenAICompatibleEmbeddingProvider(api_key=api_key, model_name=model_name)


async def embed_guideline_document(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    document_id: uuid.UUID,
    provider: EmbeddingProvider | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> BrandGuidelineDocument:
    """Generate and persist vector embeddings for all chunks of a guideline document.

    Requirements:
    - Scoped strictly to organisation, brand kit, and draft version.
    - Operates on existing PARSED chunks without requiring document re-upload.
    - Validates 1024 dimensions on all vectors before writing to database.
    - Updates document status to EMBEDDED only if real (non-mock) provider is used.
    """
    # 1. Authoritative ownership & draft validation
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
    if version.status != BrandKitVersionStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Brand Kit version is {version.status} and immutable. Chunks can only be embedded on DRAFT versions.",
        )

    # 2. Retrieve document with row lock
    stmt = (
        select(BrandGuidelineDocument)
        .where(
            BrandGuidelineDocument.id == document_id,
            BrandGuidelineDocument.brand_kit_version_id == version_id,
            BrandGuidelineDocument.organisation_id == organisation_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    doc = db.execute(stmt).scalar_one_or_none()
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Guideline document not found in this version.",
        )

    # 3. Resolve active embedding provider
    active_provider = provider or get_embedding_provider()
    if active_provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Embedding provider is not configured. Set LLM_API_KEY in environment or .env.",
        )

    # 4. Fetch document chunks ordered by chunk_index
    chunks_stmt = (
        select(BrandDocumentChunk)
        .where(
            BrandDocumentChunk.document_id == document_id,
            BrandDocumentChunk.brand_kit_version_id == version_id,
            BrandDocumentChunk.organisation_id == organisation_id,
        )
        .order_by(BrandDocumentChunk.chunk_index.asc())
        .with_for_update()
    )
    chunks = list(db.execute(chunks_stmt).scalars().all())
    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Guideline document contains no chunks to embed. Ensure document has been parsed first.",
        )

    # 5. Process chunks in bounded batches guarded by semaphore
    semaphore = get_embedding_semaphore()
    batch_size = max(1, min(batch_size, MAX_BATCH_SIZE))
    total_chunks = len(chunks)

    try:
        async with semaphore:
            for start_idx in range(0, total_chunks, batch_size):
                batch_chunks = chunks[start_idx : start_idx + batch_size]
                texts = [c.content for c in batch_chunks]

                # Generate embeddings with retries
                embeddings: list[list[float]] | None = None
                last_err: Exception | None = None

                for attempt in range(1, MAX_EMBEDDING_RETRIES + 1):
                    try:
                        embeddings = await active_provider.embed_texts(texts)
                        break
                    except (DimensionMismatchError, ProviderNotConfiguredError):
                        # Non-retryable errors
                        raise
                    except Exception as exc:
                        last_err = exc
                        if attempt < MAX_EMBEDDING_RETRIES:
                            await asyncio.sleep(0.5 * attempt)

                if embeddings is None:
                    raise ProviderAPIError(f"Embedding generation failed after {MAX_EMBEDDING_RETRIES} attempts: {last_err}")

                if len(embeddings) != len(batch_chunks):
                    raise ProviderAPIError(
                        f"Provider returned {len(embeddings)} vectors for batch of {len(batch_chunks)} chunks."
                    )

                # Persist embeddings and update chunk metadata
                for chunk_obj, vec in zip(batch_chunks, embeddings):
                    chunk_obj.embedding = vec
                    chunk_obj.embedding_model = active_provider.model_name
                    chunk_obj.embedding_model_version = "1.0"
                    chunk_obj.embedding_dimension = EXPECTED_EMBEDDING_DIMENSION

                    # Update metadata JSON with provider telemetry
                    meta = dict(chunk_obj.metadata_json or {})
                    meta["is_mock_embedding"] = active_provider.is_mock
                    meta["embedded_at"] = utcnow().isoformat()
                    chunk_obj.metadata_json = meta

                db.flush()

        # 6. Update document status
        doc.embedding_model = active_provider.model_name
        doc.embedding_model_version = "1.0"
        doc.last_error_code = None
        doc.last_error_message = None

        if active_provider.is_mock:
            # MANDATORY RULE: Never mark mock embeddings as EMBEDDED
            logger.warning(
                "Document %s embedded with MockEmbeddingProvider: keeping status '%s' (not marking EMBEDDED)",
                doc.id,
                doc.parsing_status,
            )
        else:
            doc.parsing_status = DocumentParsingStatus.EMBEDDED
            doc.embedded_at = utcnow()

        # 7. Record audit log
        audit = BrandAuditLog(
            id=uuid.uuid4(),
            organisation_id=organisation_id,
            actor_user_id=doc.uploaded_by_user_id,
            brand_kit_id=brand_kit_id,
            action="GUIDELINE_DOCUMENT_EMBEDDED",
            resource_type=BrandAuditResourceType.BRAND_KIT,
            resource_id=doc.id,
            details_json={
                "chunks_embedded": total_chunks,
                "provider": active_provider.provider_name,
                "model": active_provider.model_name,
                "dimension": EXPECTED_EMBEDDING_DIMENSION,
                "is_mock": active_provider.is_mock,
            },
        )
        db.add(audit)
        db.commit()
        db.refresh(doc)
        return doc

    except DimensionMismatchError as dme:
        db.rollback()
        doc.last_error_code = "DIMENSION_MISMATCH"
        doc.last_error_message = str(dme)[:500]
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Embedding generation aborted: {dme}",
        ) from dme
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY if isinstance(exc, ProviderAPIError) else status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Embedding failure: {exc}",
        ) from exc
