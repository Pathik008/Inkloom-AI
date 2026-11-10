"""Tenant-isolated pgvector semantic retrieval service (Phase 6.2).

Performs cosine-similarity candidate chunk retrieval with:
- Strict composite SQL scoping: (organisation_id, brand_kit_version_id).
- PostgreSQL pgvector `<=>` cosine distance ranking.
- Cosine similarity threshold bounding (defaults to >= 0.72).
- Offline SQLite fallback for local test execution.
- Deterministic empty-response fallback when AI provider is unconfigured.
"""
from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from typing import Any, List

from sqlalchemy import and_, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.brand import (
    BrandDocumentChunk,
    BrandGuidelineDocument,
    DocumentParsingStatus,
)
from app.services.rag.embedding_service import (
    EmbeddingProvider,
    get_embedding_provider,
)

DEFAULT_TOP_K = 8
DEFAULT_SIMILARITY_THRESHOLD = 0.72


@dataclass(frozen=True)
class RetrievedChunk:
    """Structure for a semantically retrieved candidate chunk."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    chunk_index: int
    page_number: int | None
    section_heading: str | None
    char_start: int
    char_end: int
    content: str
    content_sha256: str
    token_count: int
    similarity_score: float
    is_mock: bool = False


def _compute_cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two float vectors in Python (SQLite fallback)."""
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (norm_a * norm_b)))


async def retrieve_candidate_chunks(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    brand_kit_version_id: uuid.UUID,
    query_text: str,
    top_k: int = DEFAULT_TOP_K,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    provider: EmbeddingProvider | None = None,
    allow_unembedded_docs: bool = False,
) -> list[RetrievedChunk]:
    """Retrieve semantically relevant guideline document chunks.

    Guarantees:
    - Never returns chunks from other organisations or other brand kit versions.
    - If provider is unavailable, returns empty list (no fabricated semantic matches).
    """
    clean_query = (query_text or "").strip()
    if not clean_query:
        return []

    # 1. Resolve embedding provider
    active_provider = provider or get_embedding_provider()
    if active_provider is None:
        # Fallback: No credentials configured -> zero citations/chunks returned
        return []

    # 2. Embed the query text
    query_vector = await active_provider.embed_query(clean_query)
    query_vector = active_provider.validate_vector(query_vector)

    is_sqlite = db.bind.dialect.name == "sqlite" if db.bind else False

    # 3. Retrieve chunks based on database engine
    if is_sqlite:
        return _retrieve_sqlite_fallback(
            db,
            organisation_id=organisation_id,
            brand_kit_version_id=brand_kit_version_id,
            query_vector=query_vector,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
            is_mock=active_provider.is_mock,
            allow_unembedded_docs=allow_unembedded_docs,
        )
    else:
        return _retrieve_pgvector(
            db,
            organisation_id=organisation_id,
            brand_kit_version_id=brand_kit_version_id,
            query_vector=query_vector,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
            is_mock=active_provider.is_mock,
            allow_unembedded_docs=allow_unembedded_docs,
        )


def _retrieve_pgvector(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    brand_kit_version_id: uuid.UUID,
    query_vector: list[float],
    top_k: int,
    similarity_threshold: float,
    is_mock: bool,
    allow_unembedded_docs: bool,
) -> list[RetrievedChunk]:
    """Execute native PostgreSQL pgvector cosine similarity retrieval using `<=>` operator."""
    # pgvector cosine distance: d = 1 - cos(theta)
    # Cosine similarity: s = 1 - d
    # Threshold check: (1 - (embedding <=> :query_vector)) >= :similarity_threshold
    status_filter = []
    if not allow_unembedded_docs and not is_mock:
        status_filter.append(BrandGuidelineDocument.parsing_status == DocumentParsingStatus.EMBEDDED)

    distance_expr = BrandDocumentChunk.embedding.cosine_distance(query_vector)
    similarity_expr = (1.0 - distance_expr).label("similarity_score")

    stmt = (
        select(
            BrandDocumentChunk,
            BrandGuidelineDocument.title.label("doc_title"),
            similarity_expr,
        )
        .join(
            BrandGuidelineDocument,
            and_(
                BrandDocumentChunk.document_id == BrandGuidelineDocument.id,
                BrandDocumentChunk.brand_kit_version_id == BrandGuidelineDocument.brand_kit_version_id,
                BrandDocumentChunk.organisation_id == BrandGuidelineDocument.organisation_id,
            ),
        )
        .where(
            BrandGuidelineDocument.organisation_id == organisation_id,
            BrandGuidelineDocument.brand_kit_version_id == brand_kit_version_id,
            BrandDocumentChunk.organisation_id == organisation_id,
            BrandDocumentChunk.brand_kit_version_id == brand_kit_version_id,
            BrandDocumentChunk.embedding.is_not(None),
            *status_filter,
            similarity_expr >= similarity_threshold,
        )
        .order_by(distance_expr.asc())
        .limit(top_k)
    )

    rows = db.execute(stmt).all()
    results: list[RetrievedChunk] = []
    for chunk, doc_title, sim_score in rows:
        results.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_title=doc_title,
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                section_heading=chunk.section_heading,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                content=chunk.content,
                content_sha256=chunk.content_sha256,
                token_count=chunk.token_count,
                similarity_score=round(float(sim_score), 4),
                is_mock=is_mock,
            )
        )
    return results


def _retrieve_sqlite_fallback(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    brand_kit_version_id: uuid.UUID,
    query_vector: list[float],
    top_k: int,
    similarity_threshold: float,
    is_mock: bool,
    allow_unembedded_docs: bool,
) -> list[RetrievedChunk]:
    """Offline SQLite in-memory cosine ranking over unpacked vectors for local unit tests."""
    status_filter = []
    if not allow_unembedded_docs and not is_mock:
        status_filter.append(BrandGuidelineDocument.parsing_status == DocumentParsingStatus.EMBEDDED)

    stmt = (
        select(
            BrandDocumentChunk,
            BrandGuidelineDocument.title.label("doc_title"),
        )
        .join(
            BrandGuidelineDocument,
            and_(
                BrandDocumentChunk.document_id == BrandGuidelineDocument.id,
                BrandDocumentChunk.brand_kit_version_id == BrandGuidelineDocument.brand_kit_version_id,
                BrandDocumentChunk.organisation_id == BrandGuidelineDocument.organisation_id,
            ),
        )
        .where(
            BrandGuidelineDocument.organisation_id == organisation_id,
            BrandGuidelineDocument.brand_kit_version_id == brand_kit_version_id,
            BrandDocumentChunk.organisation_id == organisation_id,
            BrandDocumentChunk.brand_kit_version_id == brand_kit_version_id,
            BrandDocumentChunk.embedding.is_not(None),
            *status_filter,
        )
    )

    rows = db.execute(stmt).all()
    scored_candidates: list[tuple[float, BrandDocumentChunk, str]] = []

    for chunk, doc_title in rows:
        vec_raw = chunk.embedding
        if isinstance(vec_raw, str):
            try:
                vec = json.loads(vec_raw)
            except Exception:
                continue
        elif isinstance(vec_raw, (list, tuple)):
            vec = list(vec_raw)
        else:
            continue

        sim = _compute_cosine_similarity(query_vector, vec)
        if sim >= similarity_threshold:
            scored_candidates.append((sim, chunk, doc_title))

    # Sort descending by similarity
    scored_candidates.sort(key=lambda x: x[0], reverse=True)
    top_candidates = scored_candidates[:top_k]

    results: list[RetrievedChunk] = []
    for sim, chunk, doc_title in top_candidates:
        results.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_title=doc_title,
                chunk_index=chunk.chunk_index,
                page_number=chunk.page_number,
                section_heading=chunk.section_heading,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                content=chunk.content,
                content_sha256=chunk.content_sha256,
                token_count=chunk.token_count,
                similarity_score=round(float(sim), 4),
                is_mock=is_mock,
            )
        )
    return results

