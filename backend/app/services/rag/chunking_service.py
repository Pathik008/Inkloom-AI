"""Sentence-aware document chunking service (Phase 6.1).

Splits extracted guideline document text into bounded, sentence-aligned chunks
with sliding-window token overlap, SHA-256 hashes, exact character offsets,
and page/section metadata.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any

from app.models.brand import BrandDocumentChunk

# Default RAG token parameters
DEFAULT_CHUNK_TARGET_TOKENS = 512
DEFAULT_CHUNK_OVERLAP_TOKENS = 64
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-large-en-v1.5"
DEFAULT_EMBEDDING_VERSION = "1.5"
DEFAULT_EMBEDDING_DIMENSION = 1024

# Regex patterns for sentence and paragraph boundaries
_SENTENCE_BOUNDARY_REGEX = re.compile(
    r"(?:(?<=[.!?])\s+(?=[A-Z0-9\"'\(\[\$₹]))|(?:\r?\n\s*\r?\n+)"
)
_WORD_REGEX = re.compile(r"\w+|[^\w\s]")
_HEADING_REGEX = re.compile(r"^(?:#{1,6}\s+|[A-Z0-9\s\-_:]{3,60}$)", re.MULTILINE)


def estimate_token_count(text: str) -> int:
    """Accurately estimate token count for chunk sizing."""
    if not text or not text.strip():
        return 0
    # Uses word + punctuation count which closely matches BPE tokenizers (~1.25x words)
    tokens = len(_WORD_REGEX.findall(text))
    return max(1, tokens)


@dataclass
class TextSegment:
    """A sentence or clause segment with its exact span in the source text."""
    text: str
    char_start: int
    char_end: int
    token_count: int


def _split_into_segments(text: str, max_segment_tokens: int = 400) -> list[TextSegment]:
    """Break source text into sentence segments while recording exact character offsets.

    If a single sentence exceeds max_segment_tokens, it is broken at clause or word boundaries.
    """
    segments: list[TextSegment] = []
    text_len = len(text)
    if text_len == 0:
        return segments

    # Find split positions
    split_indices = [0]
    for match in _SENTENCE_BOUNDARY_REGEX.finditer(text):
        split_indices.append(match.start())
        split_indices.append(match.end())
    split_indices.append(text_len)

    # Deduplicate and sort
    split_indices = sorted(set(split_indices))

    for i in range(len(split_indices) - 1):
        start = split_indices[i]
        end = split_indices[i + 1]
        raw_segment = text[start:end]
        stripped = raw_segment.strip()
        if not stripped:
            continue

        # Find the exact offsets of the stripped content
        rel_start = raw_segment.find(stripped)
        seg_start = start + rel_start
        seg_end = seg_start + len(stripped)
        seg_text = text[seg_start:seg_end]
        seg_tokens = estimate_token_count(seg_text)

        # If a single sentence exceeds max_segment_tokens, subdivide it at word boundaries
        if seg_tokens > max_segment_tokens:
            sub_segments = _subdivide_oversized_segment(text, seg_start, seg_end, max_segment_tokens)
            segments.extend(sub_segments)
        else:
            segments.append(
                TextSegment(
                    text=seg_text,
                    char_start=seg_start,
                    char_end=seg_end,
                    token_count=seg_tokens,
                )
            )

    return segments


def _subdivide_oversized_segment(
    full_text: str, start: int, end: int, max_tokens: int
) -> list[TextSegment]:
    """Break a giant sentence or paragraph into smaller word-aligned segments."""
    sub_segments: list[TextSegment] = []
    seg_text = full_text[start:end]
    words = list(re.finditer(r"\S+", seg_text))
    if not words:
        return sub_segments

    current_words = []
    current_tokens = 0

    for w_match in words:
        word = w_match.group()
        w_tokens = estimate_token_count(word)
        if current_words and (current_tokens + w_tokens > max_tokens):
            w_start = start + current_words[0].start()
            w_end = start + current_words[-1].end()
            chunk_str = full_text[w_start:w_end]
            sub_segments.append(
                TextSegment(
                    text=chunk_str,
                    char_start=w_start,
                    char_end=w_end,
                    token_count=current_tokens,
                )
            )
            current_words = [w_match]
            current_tokens = w_tokens
        else:
            current_words.append(w_match)
            current_tokens += w_tokens

    if current_words:
        w_start = start + current_words[0].start()
        w_end = start + current_words[-1].end()
        chunk_str = full_text[w_start:w_end]
        sub_segments.append(
            TextSegment(
                text=chunk_str,
                char_start=w_start,
                char_end=w_end,
                token_count=current_tokens,
            )
        )

    return sub_segments


def _detect_section_heading(text_before_chunk: str, chunk_text: str) -> str | None:
    """Detect section heading preceding or at the beginning of the chunk."""
    # Check if the chunk itself starts with a Markdown heading or title line
    first_line = chunk_text.split("\n", 1)[0].strip()
    if 3 <= len(first_line) <= 80:
        if first_line.startswith("#") or first_line.isupper() or first_line.endswith(":"):
            return re.sub(r"^#+\s*", "", first_line).strip()

    # Search backwards in text_before_chunk for the most recent heading
    headings = list(_HEADING_REGEX.finditer(text_before_chunk))
    if headings:
        last_heading = headings[-1].group().strip()
        cleaned = re.sub(r"^#+\s*", "", last_heading).strip()
        if 3 <= len(cleaned) <= 80:
            return cleaned

    return None


def _resolve_page_number(
    char_start: int, page_metadata: list[dict[str, Any]] | None
) -> int | None:
    """Map character start offset to the corresponding page number if page telemetry exists.

    Accounts for the 2-character '\\n\\n' separator between extracted non-empty pages (CR-61-03).
    """
    if not page_metadata:
        return None

    non_empty_pages = [p for p in page_metadata if p.get("text", "").strip()]
    if not non_empty_pages:
        return page_metadata[0].get("page_number", 1) if page_metadata else None

    if len(non_empty_pages) == 1:
        return non_empty_pages[0].get("page_number", 1)

    cumulative_offset = 0
    for idx, page in enumerate(non_empty_pages):
        page_num = page.get("page_number", 1)
        page_len = len(page.get("text", "").strip())
        next_sep_len = 2 if idx < len(non_empty_pages) - 1 else 0
        page_end = cumulative_offset + page_len

        # If char_start falls within this page's content or within the trailing page boundary separator
        if cumulative_offset <= char_start < page_end + next_sep_len:
            return page_num

        cumulative_offset = page_end + next_sep_len

    return non_empty_pages[-1].get("page_number", 1)


@dataclass
class ChunkSpec:
    """Structured in-memory chunk specification."""
    chunk_index: int
    char_start: int
    char_end: int
    content: str
    content_sha256: str
    token_count: int
    page_number: int | None
    section_heading: str | None
    metadata_json: dict[str, Any]


def generate_chunk_specs(
    text: str,
    target_tokens: int = DEFAULT_CHUNK_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_CHUNK_OVERLAP_TOKENS,
    page_metadata: list[dict[str, Any]] | None = None,
) -> list[ChunkSpec]:
    """Generate in-memory ChunkSpec items from raw text with sliding-window overlap."""
    clean_text = text.strip()
    if not clean_text:
        return []

    segments = _split_into_segments(text)
    if not segments:
        return []

    chunks: list[ChunkSpec] = []
    chunk_index = 0
    seg_idx = 0
    num_segments = len(segments)

    while seg_idx < num_segments:
        accumulated_segments: list[TextSegment] = []
        accumulated_tokens = 0

        # Build chunk up to target_tokens
        curr = seg_idx
        while curr < num_segments:
            seg = segments[curr]
            # If adding this segment exceeds target and we already have at least one segment, stop
            if accumulated_segments and (accumulated_tokens + seg.token_count > target_tokens):
                break
            accumulated_segments.append(seg)
            accumulated_tokens += seg.token_count
            curr += 1

        if not accumulated_segments:
            break

        c_start = accumulated_segments[0].char_start
        c_end = accumulated_segments[-1].char_end
        chunk_content = text[c_start:c_end]
        c_tokens = max(1, accumulated_tokens)
        c_sha256 = hashlib.sha256(chunk_content.encode("utf-8")).hexdigest()

        text_before = text[:c_start]
        heading = _detect_section_heading(text_before, chunk_content)
        page_num = _resolve_page_number(c_start, page_metadata)

        chunks.append(
            ChunkSpec(
                chunk_index=chunk_index,
                char_start=c_start,
                char_end=c_end,
                content=chunk_content,
                content_sha256=c_sha256,
                token_count=c_tokens,
                page_number=page_num,
                section_heading=heading,
                metadata_json={
                    "char_length": len(chunk_content),
                    "segment_count": len(accumulated_segments),
                    "token_estimate": c_tokens,
                },
            )
        )
        chunk_index += 1

        # Calculate overlap for the next chunk
        if curr >= num_segments:
            # Reached end of text
            break

        # Backtrack segments from the tail to provide overlap_tokens
        overlap_accum = 0
        backtrack_idx = curr
        for b_idx in range(curr - 1, seg_idx, -1):
            overlap_accum += segments[b_idx].token_count
            if overlap_accum >= overlap_tokens:
                backtrack_idx = b_idx
                break
            backtrack_idx = b_idx

        # Guard against zero-progress: ensure we advance at least 1 segment
        seg_idx = max(seg_idx + 1, backtrack_idx)

    return chunks


def chunk_document_text(
    *,
    text: str,
    document_id: uuid.UUID,
    brand_kit_version_id: uuid.UUID,
    organisation_id: uuid.UUID,
    target_tokens: int = DEFAULT_CHUNK_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_CHUNK_OVERLAP_TOKENS,
    page_metadata: list[dict[str, Any]] | None = None,
) -> list[BrandDocumentChunk]:
    """Produce SQLAlchemy BrandDocumentChunk ORM instances ready for database persistence."""
    specs = generate_chunk_specs(
        text,
        target_tokens=target_tokens,
        overlap_tokens=overlap_tokens,
        page_metadata=page_metadata,
    )

    orm_chunks: list[BrandDocumentChunk] = []
    for spec in specs:
        chunk = BrandDocumentChunk(
            id=uuid.uuid4(),
            document_id=document_id,
            brand_kit_version_id=brand_kit_version_id,
            organisation_id=organisation_id,
            chunk_index=spec.chunk_index,
            page_number=spec.page_number,
            section_heading=spec.section_heading,
            char_start=spec.char_start,
            char_end=spec.char_end,
            content=spec.content,
            content_sha256=spec.content_sha256,
            token_count=spec.token_count,
            embedding=None,  # Populated in Phase 6.2
            embedding_model=DEFAULT_EMBEDDING_MODEL,
            embedding_model_version=DEFAULT_EMBEDDING_VERSION,
            embedding_dimension=DEFAULT_EMBEDDING_DIMENSION,
            metadata_json=spec.metadata_json,
        )
        orm_chunks.append(chunk)

    return orm_chunks
