# Inkloom AI — Phase 6: RAG & AI Engine Integration Plan (v1.1)

**Document Version:** 1.1.0  
**Status:** REVISED ARCHITECTURAL PLAN (Awaiting User Approval)  
**Target Branch:** `phase3-brand-hub`  
**Prerequisites:** Phase 5.4 Security & Reliability Remediation Complete (141 Tests Passing, CodeRabbit PASS)  
**Core Objective:** Revised architecture, schema alignment, and execution blueprint for the Hybrid Compliance Engine (Deterministic Rules + pgvector Semantic RAG + LangGraph Review Workflow), incorporating all mandatory architectural corrections.

---

## 1. Executive Summary & Revised Architecture

Inkloom AI's core compliance engine operates on a **hybrid, fail-safe architecture** that marries deterministic precision with grounded semantic analysis:

1. **Deterministic Rule Engine (Phase 5 — Unchanged & Authoritative):**
   - High-throughput, zero-hallucination regex and word-boundary matching.
   - Evaluates exact prohibited terms, mandatory disclaimers, brand identity rules, and exact fact discrepancies.
   - Computes the primary, authoritative `deterministic_score` ($0 - 100$) using the established penalty formula.
2. **pgvector Semantic RAG Subsystem (Phase 6):**
   - Semantic similarity search over approved Brand Guideline Documents.
   - Restricted strictly to real 1024-dimensional embedding models in production (`BAAI/bge-large-en-v1.5` or OpenAI-compatible).
   - Mock embeddings are strictly quarantined to infrastructure verification and offline unit tests, explicitly tagged as `non_semantic`.
3. **LangGraph Review Workflow (Phase 6):**
   - Implements 11 logical review stages organized into cohesive, conditionally routed state graph nodes.
   - Extracts marketing claims, retrieves tenant/version-isolated evidence, verifies facts, and audits brand tone.
   - Enforces the **Unverified Guard**: every citation is validated against actual database chunk IDs; ungrounded statements are strictly classified as `UNVERIFIED_CLAIM`.
   - Produces a distinct `semantic_assessment` telemetry block without distorting or double-counting the deterministic compliance score.
4. **Resilient Fallback Mode:**
   - If AI credentials are missing, external APIs time out, or the LLM fails, the system executes deterministic-only analysis, returning `engine_mode = "DETERMINISTIC_FALLBACK"` with 100% platform availability.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                Submitted Marketing Copy                                │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                     Stage 1: Input Ingestion & Span Normalization                      │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                   Stage 2: Deterministic Rule Evaluation (Authoritative)                │
│    • Regex / Word-Boundary matching on Prohibited Words & Mandatory Disclaimers        │
│    • Computes authoritative deterministic_score (0 - 100, PASS threshold 70)          │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
                         [Check AI Provider Available?]
                                 /                \
                       YES (Active)              NO / Failed
                             /                      \
                            ▼                        ▼
┌───────────────────────────────────────┐   ┌────────────────────────────────────────────┐
│ Stage 3: Claim Extraction (Max 15)    │   │ Bypass Semantic Evaluation                 │
└──────────────────┬────────────────────┘   │ • Set engine_mode = DETERMINISTIC_FALLBACK │
                   │                        │ • Zero invented tone or fact findings      │
                   ▼                        │ • Clear AI availability status in telemetry│
┌───────────────────────────────────────┐   └─────────────────────┬──────────────────────┘
│ Stage 4: Batch Vector Evidence Retrieval  │                     │
│ • pgvector 1024-d, Tenant + Version   │                         │
│ • Capped at 12 unique chunks total    │                         │
└──────────────────┬────────────────────┘                         │
                   │                                              │
                   ▼                                              │
┌───────────────────────────────────────┐                         │
│ Stage 5: Fact Verification & Grounding│                         │
└──────────────────┬────────────────────┘                         │
                   │                                              │
                   ▼                                              │
┌───────────────────────────────────────┐                         │
│ Stage 6: Tone & Voice Assessment      │                         │
└──────────────────┬────────────────────┘                         │
                   │                                              │
                   ▼                                              │
┌───────────────────────────────────────┐                         │
│ Stage 7: Unverified Guard             │                         │
│ • DB validation of candidate chunk IDs│                         │
│ • Unsupported claims marked UNVERIFIED│                         │
└──────────────────┬────────────────────┘                         │
                   │                                              │
                   ▼                                              │
┌───────────────────────────────────────┐                         │
│ Stage 8: Semantic Deduplication       │                         │
│ • Prevent double-counting of Phase 5  │                         │
└──────────────────┬────────────────────┘                         │
                   │                                              │
                   ▼                                              │
┌───────────────────────────────────────┐                         │
│ Stage 9: Remediation Generation       │                         │
└──────────────────┬────────────────────┘                         │
                   │                                              │
                   ▼                                              │
┌───────────────────────────────────────┐                         │
│ Stage 10: Pydantic v2 Schema Synthesis│                         │
└──────────────────┬────────────────────┘                         │
                   │                                              │
                   ▼                                              │
┌───────────────────────────────────────┐                         │
│ Stage 11: Final Packaging & DB Store  │◄────────────────────────┘
│ • Reuses existing ComplianceAnalysis  │
└───────────────────────────────────────┘
```

---

## 2. Mandatory Architectural Corrections

### 2.1 Mock vs. Real Semantic Embeddings
- **Mock Embedding Quarantine:**  
  SHA-256 pseudo-random vectors are **strictly quarantined** to database migration checks, pipeline integrity verification, and offline in-memory SQLite unit tests. They must **never** be presented or logged as semantic embeddings.
- **Explicit Metadata Tagging:**  
  When running under test or fallback mode, all mock-generated chunk embeddings are tagged in `metadata_json` with `"embedding_provider": "mock"` and `"non_semantic": true`.
- **Live Semantic Requirements:**  
  Production and staging environments must use genuine semantic embedding models producing 1024-dimensional vectors (`BAAI/bge-large-en-v1.5` via HuggingFace Inference API or compatible provider).
- **Startup & Ingestion Dimension Validation:**  
  At application startup and prior to chunk ingestion, the system validates that the configured embedding service produces vectors matching `EMBEDDING_DIMENSION == 1024` and `ck_brand_doc_chunks_embedding_dim`. Any mismatch immediately halts processing with a structured `422 Unprocessable Entity` or startup configuration error.

### 2.2 Scoring Integrity & Deduplication
- **Authoritative Deterministic Score:**  
  The primary compliance score ($0 - 100$, pass threshold $70$) remains strictly computed by the deterministic engine using existing penalty weights (`CRITICAL: 40`, `HIGH: 20`, `MEDIUM: 10`, `LOW: 5`).
- **Separate Semantic Assessment:**  
  AI semantic findings are segregated into an independent `semantic_assessment` dictionary inside `scoring_json`:
  ```json
  {
    "formula": "100 - sum(deterministic_penalties)",
    "deterministic_score": 80,
    "deterministic_result": "PASS",
    "semantic_assessment": {
      "claims_evaluated": 4,
      "claims_verified": 2,
      "claims_unverified": 1,
      "claims_contradicted": 1,
      "tone_grade": "ACCEPTABLE",
      "tone_feedback": "Tone matches professional guidelines with slight informal drift in paragraph 2."
    }
  }
  ```
- **Overlap Deduplication:**  
  If a deterministic rule already detected a violation on a specific character span (e.g., an exact price mismatch like `₹99` vs `₹129`), the semantic engine must check existing findings before flagging. If an overlapping deterministic finding exists, the semantic engine annotates the existing finding with evidence rather than creating a duplicate finding or subtracting duplicate penalty points.
- **Future Combined Score Protocol:**  
  If an experimental combined score is requested via query flag (`include_experimental_score=true`), it is calculated additively as:
  $$\text{experimental\_score} = \max\left(0, \text{deterministic\_score} - (20 \times \text{semantic\_contradictions}) - (10 \times \text{unverified\_claims})\right)$$
  The base `score` column on `ComplianceAnalysis` remains 100% deterministic to guarantee backwards compatibility and zero-drift regression safety.

### 2.3 Unverified Guard & Citation Validation
- **Zero Hallucination Rule:**  
  The LLM is strictly prohibited from fabricating or guessing citation IDs, document references, or confidence metrics.
- **Cryptographic & Relational Validation:**  
  Every citation proposed in a semantic finding must pass rigorous server-side database validation against the actual set of chunks retrieved for that submission:
  1. `citation.chunk_id` must exist in `retrieved_chunk_ids`.
  2. `chunk.organisation_id` must match `context.organisation.id`.
  3. `chunk.brand_kit_version_id` must match the submission's `brand_kit_version_id`.
  4. `chunk.document_id` must reference an approved document in that version.
- **Fallback to UNVERIFIED:**  
  If any claim lacks supporting retrieved chunks, or if the model cites a chunk that fails database validation, the citation is stripped and the claim is classified as `kind = "UNVERIFIED_CLAIM"` with explanation: `"This marketing claim could not be verified against any approved brand guideline document or fact."`

### 2.4 Deterministic Fallback Mode
- **Zero-Failure Guarantee:**  
  If `LLM_API_KEY` is not configured, or if the external model times out, returns an HTTP error, or outputs malformed JSON, the compliance pipeline degrades gracefully to deterministic-only evaluation.
- **Zero Fabricated Findings:**  
  In fallback mode, the system **never** invents tone scores, semantic claims, or factual verifications.
- **Explicit Telemetry:**  
  The analysis response explicitly sets:
  - `engine_mode: "DETERMINISTIC_FALLBACK"`
  - `ai_available: false`
  - `ai_status_message: "Semantic review bypassed: AI provider unconfigured or unreachable."`

### 2.5 Upload Security & 10 MB Bound
- **Strict 10 MB Boundary:**  
  Guideline document uploads will strictly respect the established **10 MB limit** (`10,485,760` bytes) from Phase 5.3 across all formats (PDF, DOCX, TXT), preventing unbounded memory growth or decompression strain.
- **Preserved Hardening:**  
  All security defenses from Phase 5.3 and 5.4 are preserved:
  - Bounded 64 KB chunked streaming reads.
  - Extension and magic-byte verification (`%PDF-`, `PK\x03\x04` with DOCX XML hierarchy, clean UTF-8).
  - ZIP bomb defense: 1000 max entries, 50:1 max compression ratio, 20 MB max uncompressed entry.
  - PDF limits: 100 pages, 2,000,000 max characters.
  - Threadpool concurrency limit: max 5 concurrent extraction/chunking jobs via shared semaphore.
  - Canonical storage path containment: `is_relative_to(upload_root)` and `is_relative_to(org_dir)`.
  - Immediate unlinking of partial `.part` staging files on failure.

### 2.6 Multi-Tenant & Multi-Version Vector Isolation
- **No Reliance on Client-Supplied Identifiers:**  
  The retrieval service never blindly trusts `organisation_id` or `brand_kit_version_id` from client payloads.
- **Authoritative Entity Verification:**  
  The system verifies that:
  1. The authenticated user holds active membership in the target organisation.
  2. The target `brand_kit_id` belongs to `context.organisation.id`.
  3. The target `brand_kit_version_id` belongs to `brand_kit_id` and is in `PUBLISHED` status (or `DRAFT` for pre-publish authoring tests).
- **Strict SQL Filtering:**  
  All retrieval queries on `brand_document_chunks` explicitly join `brand_guideline_documents` and enforce:
  ```sql
  WHERE brand_document_chunks.organisation_id = :org_id
    AND brand_document_chunks.brand_kit_version_id = :version_id
  ```
- **Leakage Prevention Tests:**  
  Automated tests must explicitly verify that Tenant B querying with identical embedding text receives zero results from Tenant A, and Version 2 querying receives zero results from Version 1 chunks that were modified or removed.

### 2.7 Database Schema & Model Reuse
- **Zero Duplicate Schema Structures:**  
  The implementation reuses the existing, battle-tested Phase 4/5 models:
  - `ContentSubmission` in `backend/app/models/compliance.py`
  - `ComplianceAnalysis` in `backend/app/models/compliance.py`
  - `BrandGuidelineDocument` in `backend/app/models/brand.py`
  - `BrandDocumentChunk` in `backend/app/models/brand.py`
- **Existing `DocumentParsingStatus` Alignment:**  
  The existing enum values in `backend/app/models/brand.py` are strictly adhered to:
  `'PENDING'`, `'PROCESSING'`, `'PARSED'`, `'COMPLETED'`, `'EMBEDDED'`, `'FAILED'`.
  No new database enum states will be introduced.
- **Finding Model Flexibility:**  
  Semantic findings are stored directly in `ComplianceAnalysis.findings_json` with `source: "RAG_SEMANTIC"` or `source: "TONE_ANALYSIS"`, matching the established JSON structure without requiring schema migration.

### 2.8 LangGraph Architecture & Node Justification
The 11 logical stages are structured into maintainable LangGraph state graph nodes with clear separation of concerns, conditional branching, and error handling:

| Node | Logical Stage Covered | Purpose & Responsibilities | Conditional Routing / Fallback |
| :--- | :--- | :--- | :--- |
| **`ingest_and_normalize`** | Stage 1 | Normalize text whitespace, compute content SHA-256, map character offset indices. | If text empty or exceeds 50k chars, abort with 422. |
| **`deterministic_engine`** | Stage 2 | Call `compliance_engine.evaluate_content()`. Pure functional evaluation of exact rules. | Always executes. If AI unavailable, route directly to `final_synthesis`. |
| **`claim_extractor`** | Stage 3 | Extract factual claims, pricing claims, and superlative claims. Capped at 15 claims. | If 0 claims extracted or AI provider disabled, bypass RAG and route to `tone_auditor`. |
| **`vector_retriever`** | Stage 4 | Batch query `pgvector` for candidate chunks across all claims. Capped at 12 unique chunks. | If vector index empty or no chunks meet similarity threshold, route directly to `unverified_guard`. |
| **`fact_verifier`** | Stage 5 | Compare extracted claims against retrieved chunks and `ApprovedBrandFact` records. | Evaluates claim grounding. Errors route safely to `unverified_guard`. |
| **`tone_auditor`** | Stage 6 | Evaluate brand voice guidelines against `BrandIdentity.brand_voice_guidelines`. | If brand voice guidelines unconfigured, skip with INFO notice. |
| **`unverified_guard`** | Stage 7 | Cryptographic & DB verification of chunk IDs. Unbacked claims converted to `UNVERIFIED_CLAIM`. | Mandatory security gate: strips all unverified LLM citations. |
| **`deduplicate_and_score`** | Stage 8 | Deduplicate overlapping findings with Stage 2. Calculate separate semantic summary. | Ensures deterministic score remains unaltered by semantic checks. |
| **`remediation_generator`** | Stage 9 | Generate machine-applicable text fixes (`replacement` or `append_text`). | Optional fix proposals; failures do not block analysis. |
| **`schema_validator`** | Stage 10 | Strict Pydantic v2 validation of all structured findings and scoring metrics. | If validation fails, logs error and outputs clean fallback structure. |
| **`final_synthesis`** | Stage 11 | Assemble final response and persist to `compliance_analyses` table. | Terminal node. Always succeeds and persists results. |

### 2.9 Retrieval Performance & Cost Controls
To prevent latency spikes, quadratic retrieval loops, and unbounded external LLM API costs:
1. **Max Claims per Submission:**  
   Submissions are capped at evaluating a maximum of **15 discrete claims**. If a marketing document contains more than 15 claims, the top 15 highest-risk claims (pricing, superlatives, legal promises) are prioritized, and an informational note is attached.
2. **Batch Retrieval & Top-K Bounding:**  
   - Vector search retrieves a maximum of **3 chunks per claim**.
   - The total retrieved candidate chunk pool for a submission is deduplicated and capped at **12 unique chunks**.
3. **Concurrency Semaphore:**  
   AI review execution is constrained by an `asyncio.Semaphore(5)` to prevent overloading the system or exhausting threadpool workers.
4. **Per-Call Timeout & Circuit Breaker:**  
   All external AI API calls enforce a strict **15-second timeout**. If a call times out or fails 3 consecutive times, the circuit breaker opens for 60 seconds, routing all requests to `DETERMINISTIC_FALLBACK`.

---

## 3. Work Package Execution Plan

### Work Package 6.1 — Guideline Document Ingestion & Chunking
- **Endpoints in `backend/app/api/routes/brand_kits.py`:**
  - `POST /api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/documents`:
    - Enforce `brand:manage` permission and `DRAFT` version status.
    - Enforce 10 MB upload limit and 64 KB chunked streaming.
    - Extract text via `document_extraction_service`.
    - Chunk text into 512-token segments (64-token overlap) via `chunking_service`.
    - Populate `brand_document_chunks` table with `chunk_index`, offsets, and `content_sha256`.
    - Mark document `parsing_status = 'PARSED'`.
  - `GET /api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/documents`:
    - List documents with chunk counts, token totals, and telemetry status.
  - `DELETE /api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/documents/{doc_id}`:
    - Allow deletion only from `DRAFT` versions.
  - `POST /api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/documents/{doc_id}/reparse`:
    - Retry failed parsing/chunking.

### Work Package 6.2 — Embedding Subsystem & Tenant-Isolated Vector Search
- **Embedding Service (`backend/app/services/rag/embedding_service.py`):**
  - Implement dual-provider interface:
    - `RealEmbeddingProvider`: Calls genuine embedding API (`BAAI/bge-large-en-v1.5` 1024-d).
    - `MockEmbeddingProvider`: Generates deterministic test vectors explicitly tagged as `non_semantic: true`.
  - Update `brand_guideline_documents` status to `'EMBEDDED'` upon completion.
  - Validate 1024-dimension constraint on all vectors.
- **Retriever (`backend/app/services/rag/retriever.py`):**
  - PostgreSQL `pgvector` similarity query using `<=>` cosine distance.
  - Composite filtering on `(organisation_id, brand_kit_version_id)`.
  - Cosine threshold filtering ($\ge 0.72$).
  - SQLite fallback using in-memory cosine ranking over unpacked vectors for offline unit tests.

### Work Package 6.3 — LangGraph Review Workflow & Unverified Guard
- **Workflow State & Graph (`backend/app/services/ai_workflow/compliance_graph.py`):**
  - Implement the 11 discrete stages mapped to the justified nodes.
  - Implement the **Unverified Guard**: cross-reference all proposed citations against database candidate chunks.
  - Implement **Deterministic Fallback**: graceful degradation when AI credentials or network fail.
  - Segregate deterministic compliance score from semantic telemetry.

### Work Package 6.4 — API Integration & Frontend Telemetry
- **API Updates (`backend/app/api/routes/compliance.py`):**
  - Enhance `POST /compliance/analyze` to support `mode: "hybrid" | "deterministic"`.
  - Save unified results in existing `ComplianceAnalysis` model.
- **Frontend Workbench (`frontend/src/pages/ComplianceWorkbenchPage.tsx`):**
  - Render evidence citation cards displaying document name, page number, and similarity score.
  - Display Amber `UNVERIFIED_CLAIM` badges for unbacked marketing statements.
  - Render Tone & Voice feedback section in the results panel.

---

## 4. Comprehensive Testing & Acceptance Criteria

*(Specified for implementation during Phase 6 execution; not executed now).*

| Test ID | Target Component | Verification Objective |
| :--- | :--- | :--- |
| **TEST-601** | `chunking_service.py` | Verify 512-token chunk bounds, 64-token overlap, character span accuracy, and SHA-256 calculation. |
| **TEST-602** | `embedding_service.py` | Verify 1024-dimension enforcement. Verify mock embeddings are explicitly tagged `non_semantic: true`. |
| **TEST-603** | `retriever.py` | **Cross-Tenant Isolation:** Verify Tenant B cannot retrieve Tenant A chunks. **Cross-Version Isolation:** Verify Version 2 cannot retrieve Version 1 chunks that were superseded. |
| **TEST-604** | `compliance_graph.py` | **Unverified Guard:** Verify claims lacking DB-grounded evidence are marked `UNVERIFIED_CLAIM` with zero hallucinated citations. |
| **TEST-605** | `compliance_graph.py` | **Deterministic Fallback:** Verify workflow completes with 100% deterministic score when AI keys are empty or external call fails. |
| **TEST-606** | `compliance_graph.py` | **Deduplication:** Verify overlapping deterministic and semantic findings do not double-penalize compliance score. |
| **TEST-607** | `brand_kits.py` | **Immutability & Pre-Publish:** Verify upload to `PUBLISHED` version returns 409/422. Verify publishing fails if documents are not `'EMBEDDED'`. |
| **TEST-608** | `compliance.py` | **Performance & Bounding:** Verify submissions with >15 claims are capped cleanly without timeout or unhandled exceptions. |

---

## 5. Implementation Sequence & Checkpoints

```
  ┌────────────────────────────────────────────────────────────────────────┐
  │ Checkpoint 1: Work Package 6.1 (Guideline Ingestion & Chunking)        │
  │ • Mount document routes with 10 MB limit in brand_kits.py              │
  │ • Implement 512/64 token chunker in chunking_service.py                │
  │ • Verify database insertions into brand_document_chunks                │
  └───────────────────────────────────┬────────────────────────────────────┘
                                      │
                                      ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │ Checkpoint 2: Work Package 6.2 (Embedding & Multi-Tenant Retriever)    │
  │ • Implement real embedder + mock embedder with non_semantic flag      │
  │ • Implement tenant & version-isolated pgvector retrieval in retriever.py│
  │ • Verify Pre-Publish Gate 3 (EMBEDDED requirement)                     │
  └───────────────────────────────────┬────────────────────────────────────┘
                                      │
                                      ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │ Checkpoint 3: Work Package 6.3 (LangGraph Review Workflow & Guard)     │
  │ • Build 11-stage LangGraph graph with justified nodes                  │
  │ • Implement Unverified Guard with DB chunk cross-referencing           │
  │ • Implement Deterministic Fallback & Deduplication logic               │
  └───────────────────────────────────┬────────────────────────────────────┘
                                      │
                                      ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │ Checkpoint 4: Work Package 6.4 (API Wiring, Frontend & E2E Validation) │
  │ • Connect compliance router to hybrid LangGraph workflow               │
  │ • Render citation cards and UNVERIFIED badges in frontend              │
  │ • Run comprehensive verification test suite (TEST-601 to TEST-608)     │
  └────────────────────────────────────────────────────────────────────────┘
```

---

*End of Revised Planning Document (v1.1). Awaiting user approval before proceeding with implementation.*
