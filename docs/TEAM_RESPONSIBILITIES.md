# Inkloom AI — Team Responsibilities & Integration Architecture

This project is developed by four team members for **CodeTitans India 2026 Round 2**. The architecture is modular so each member's work can be developed and tested independently while sharing unified API contracts, database models, authentication, and tenant isolation.

---

## 1. Riddhi Yadav — Frontend: Dashboard and Brand Management

### Core Responsibilities
- Main dashboard.
- Main navigation and layout.
- Brand Hub UI.
- Brand Kit management.
- Brand identity and asset management.
- Brand guidelines and configuration forms.
- Content upload interface.
- Frontend API integration for these modules.

### Primary Code Ownership
- `frontend/src/layouts/`
- `frontend/src/pages/Dashboard*`, `BrandHub*`, `BrandKit*`, `ContentUpload*`
- `frontend/src/components/brand/`, `frontend/src/components/upload/`

---

## 2. Pragati Kumari — Frontend: Compliance Review and Approval

### Core Responsibilities
- Compliance results dashboard.
- Findings and evidence panel.
- Highlighted violations.
- Content editor.
- AI correction suggestions UI.
- Approval and rejection workflow UI.
- Reviewer comments.
- Revision history.
- Analytics and reports UI.

### Primary Code Ownership
- `frontend/src/pages/ComplianceReview*`, `ContentEditor*`, `ApprovalInbox*`, `RevisionHistory*`, `Analytics*`
- `frontend/src/components/review/`, `frontend/src/components/editor/`, `frontend/src/components/approvals/`

---

## 3. Pathik Talwar — Backend: Infrastructure and Rule-Based Intelligence

### Core Responsibilities
- FastAPI backend.
- PostgreSQL architecture and schema.
- SQLAlchemy models and migrations.
- Authentication and RBAC.
- Tenant isolation and access control.
- Brand knowledge management and versioning.
- Deterministic compliance engine.
- Exact rule validation.
- Approval gate.
- SHA-256 content hashing.
- Audit logs.
- Backend API integration and testing.

### Primary Code Ownership
- `backend/app/core/`, `backend/app/database/`, `backend/app/models/`, `backend/app/schemas/`
- `backend/app/api/routes/`
- `backend/app/services/deterministic_engine.py`, `approval_gate.py`, `audit_service.py`
- `backend/alembic/`, `infra/`

---

## 4. Tanmay Mishra — AI: Multimodal Analysis and Explainability

### Core Responsibilities
- Document processing and OCR.
- Text extraction.
- RAG pipeline.
- Embeddings and vector search.
- LangGraph AI workflow.
- LLM-based semantic and tone analysis.
- Visual brand compliance analysis.
- Evidence-backed explanations.
- Severity and confidence assessment.
- Correction suggestions.

### Primary Code Ownership
- `backend/app/services/extraction/` (PyMuPDF, `python-docx`, OCR)
- `backend/app/services/rag/` (`BAAI/bge-large-en-v1.5` embeddings, chunking, `pgvector` retrieval)
- `backend/app/services/ai_workflow/` (11-node LangGraph compliance pipeline, Pydantic v2 output validators)

---

## 5. Cross-Team Integration Rules

1. **Single Unified Application**: All four domains operate within one FastAPI backend and one React + TypeScript frontend connected to a single PostgreSQL + `pgvector` database.
2. **Contract-First Integration**: All requests and responses adhere to `docs/API_CONTRACT.md` and Pydantic v2 schemas in `backend/app/schemas/`.
3. **Strict Tenant & Version Binding**: Every RAG lookup, deterministic rule evaluation, and approval gate check requires `organisation_id`, `brand_kit_version_id`, and `content_revision_id` (with SHA-256 hash verification).
