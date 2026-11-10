# Inkloom AI — Team Responsibilities & Integration Architecture

This project is developed by **Pathik Talwar** and **Pragati Kumari** for **CodeTitans India 2026 Round 2**. The architecture is modular so each member's work can be developed and tested independently while sharing unified API contracts, database models, authentication, and tenant isolation.

---

## 1. Pragati Kumari — Frontend: User Interface, Brand Hub & Compliance Review

### Core Responsibilities
- Main dashboard, navigation, and application layout.
- Brand Hub UI, Brand Kit management, and brand guidelines configuration forms.
- Brand identity and asset management interfaces.
- Content upload and multimodal file submission interfaces.
- Compliance review workbench, results dashboard, findings, and evidence panel.
- Highlighted text violations and character span rendering.
- Content editor and AI correction suggestions UI.
- Human approval and rejection workflow UI with reviewer action center.
- Reviewer comments and revision comparison diffing.
- Analytics and compliance reports UI.
- Frontend API client integration across all application modules.

### Primary Code Ownership
- `frontend/src/layouts/`
- `frontend/src/pages/`
- `frontend/src/components/`

---

## 2. Pathik Talwar — Backend: Infrastructure, Rule-Based Intelligence & AI Systems

### Core Responsibilities
- FastAPI backend architecture, endpoints, and middleware.
- PostgreSQL database architecture, relational schema, SQLAlchemy models, and Alembic migrations.
- Authentication, Argon2id password hashing, and multi-tenant RBAC.
- Tenant isolation, IDOR protection, and access control.
- Brand knowledge management and immutable versioning.
- Deterministic compliance engine and exact rule validation.
- Human approval gate, SHA-256 content hashing, and security audit logs.
- Document processing, OCR, and multimodal text extraction.
- RAG pipeline, 1024-dimensional vector embeddings, chunking, and `pgvector` retrieval.
- LangGraph 11-stage compliance workflow, semantic analysis, and evidence-backed explanations.
- Severity and confidence assessment and automated correction generation.
- Backend API integration and automated test suites.

### Primary Code Ownership
- `backend/app/core/`, `backend/app/database/`, `backend/app/models/`, `backend/app/schemas/`
- `backend/app/api/routes/`
- `backend/app/services/`
- `backend/alembic/`, `infra/`

---

## 3. Integration Rules

1. **Single Unified Application**: All functional domains operate within one FastAPI backend and one React + TypeScript frontend connected to a single PostgreSQL + `pgvector` database.
2. **Contract-First Integration**: All requests and responses adhere to `docs/API_CONTRACT.md` and Pydantic v2 schemas in `backend/app/schemas/`.
3. **Strict Tenant & Version Binding**: Every RAG lookup, deterministic rule evaluation, and approval gate check requires `organisation_id`, `brand_kit_version_id`, and `content_revision_id` (with SHA-256 hash verification).
