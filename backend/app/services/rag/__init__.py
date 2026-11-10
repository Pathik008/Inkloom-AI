"""RAG services package for Inkloom AI (Phase 6)."""
from app.services.rag.chunking_service import ChunkSpec, chunk_document_text
from app.services.rag.embedding_service import (
    DimensionMismatchError,
    EmbeddingError,
    EmbeddingProvider,
    GeminiEmbeddingProvider,
    MockEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    ProviderAPIError,
    ProviderNotConfiguredError,
    embed_guideline_document,
    get_embedding_provider,
)
from app.services.rag.retriever import RetrievedChunk, retrieve_candidate_chunks

__all__ = [
    "ChunkSpec",
    "chunk_document_text",
    "EmbeddingError",
    "DimensionMismatchError",
    "ProviderNotConfiguredError",
    "ProviderAPIError",
    "EmbeddingProvider",
    "GeminiEmbeddingProvider",
    "OpenAICompatibleEmbeddingProvider",
    "MockEmbeddingProvider",
    "get_embedding_provider",
    "embed_guideline_document",
    "RetrievedChunk",
    "retrieve_candidate_chunks",
]
