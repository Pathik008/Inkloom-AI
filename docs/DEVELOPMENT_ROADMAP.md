# Inkloom AI — 10-Phase Development Roadmap

This document tracks the incremental engineering milestones for **Inkloom AI** from initial foundation through full production readiness.

---

## Phase 1 — Foundation *(COMPLETED)*
### Objectives
- Inspect workspace and environment prerequisites.
- Create modular project structure (`frontend/`, `backend/`, `docs/`, `infra/`).
- Set up FastAPI backend with Pydantic settings, CORS, `/health`, and `/api/v1/health`.
- Configure SQLAlchemy 2.0 and Alembic migration environment.
- Prepare PostgreSQL 16 + `pgvector` Docker Compose configuration with persistent volumes.
- Create React + Vite + TypeScript + Tailwind CSS + Lucide React frontend shell.
- Connect real-time frontend health indicator to the live FastAPI health endpoint.
- Add and pass initial `pytest` backend tests and frontend TypeScript/Vite build verification.
- Complete `ARCHITECTURE.md`, `API_CONTRACT.md`, `TEAM_RESPONSIBILITIES.md`, `DEVELOPMENT_ROADMAP.md`, and `README.md`.

---

## Phase 2 — Authentication and Database *(COMPLETED)*
### Objectives & Completion Criteria
- Design relational schema in SQLAlchemy (`User`, `Organisation`, `OrganisationMembership`, `Role`, `Permission`, `RolePermission`, `RevokedToken`).
- Generate and apply Alembic migration (`0001_phase2_auth_rbac`) with repeatable role/permission seeding and PostgreSQL `pgvector` extension creation.
- Implement user registration, login, logout (`jti` revocation), `/auth/me`, and Argon2id password hashing.
- Implement multi-tenant organisation creation, member management, last-active-`ADMIN` protection, and role assignment (`ADMIN`, `BRAND_MANAGER`, `CONTENT_CREATOR`, `REVIEWER`).
- Enforce backend RBAC permissions and strict tenant isolation across all queries, plus protected frontend routes, login/register UI, and organisation settings workspace.

---

## Phase 3 — Brand Hub *(NEXT MILESTONE)*
### Objectives & Completion Criteria
- Implement Brand Kit CRUD and Brand Identity configuration (name, industry, colours, typography, guidelines).
- Implement Brand Voice configuration (tone, style, preferred/prohibited vocabulary, approved/disapproved examples).
- Implement structured, versioned Approved Brand Facts (prices, specs, offers, availability, validity dates).
- Implement configurable Compliance Rules (prohibited words, mandatory disclaimers, restricted claims, pricing rules).
- Implement Brand Asset & Document upload management.
- Implement Brand Kit Versioning (`DRAFT` vs `PUBLISHED`, version diffs, active version selection, historical review binding).

---

## Phase 4 — Content Ingestion
### Objectives & Completion Criteria
- Build rich text editor and multimodal file upload UI with size/MIME validation.
- Implement PDF extraction via PyMuPDF (`fitz`), DOCX extraction via `python-docx`, and image text extraction via OCR.
- Preserve extracted text and source metadata so findings map accurately to spans.
- Implement `ContentItem` and immutable `ContentRevision` creation with SHA-256 hashing and status tracking.

---

## Phase 5 — Deterministic Compliance Engine
### Objectives & Completion Criteria
- Build deterministic, reproducible rule evaluator independent of LLM calls.
- Detect exact price/fact mismatches (e.g., `₹99` vs approved `₹129` for `Premium Coffee`).
- Detect prohibited words/phrases, missing mandatory disclaimers (`"Terms and conditions apply."`), and mandatory terminology violations.
- Output structured `ComplianceFinding` objects with exact character spans, rule source IDs, and documented severity calculation.

---

## Phase 6 — RAG and AI Engine
### Objectives & Completion Criteria
- Extract, clean, and chunk approved Brand Kit documents (~512 tokens, ~64 tokens overlap).
- Generate 1024-dimension embeddings using `BAAI/bge-large-en-v1.5` (or documented compatible provider) and store in `pgvector`.
- Filter vector retrieval strictly by `organisation_id`, `brand_kit_id`, `brand_kit_version_id`, and `APPROVED` status.
- Implement the 11-node LangGraph workflow combining deterministic checks, semantic/tone analysis, and evidence verification.
- Enforce `UNVERIFIED` status whenever supporting approved evidence is missing; validate all outputs with Pydantic v2.

---

## Phase 7 — Findings and Suggestions
### Objectives & Completion Criteria
- Build Compliance Review Results UI showing overall status, documented compliance score formula, and severity/category filters.
- Highlight flagged spans directly in the submitted content and display supporting evidence & rule citations.
- Implement integrated Content Editor allowing creators to apply individual AI suggestions or edit manually.
- Ensure every content edit creates a new SHA-256 `ContentRevision`, invalidates any prior approval, and allows re-running compliance review.

---

## Phase 8 — Approval and Audit
### Objectives & Completion Criteria
- Implement `DRAFT → SUBMITTED → UNDER_REVIEW → APPROVED / REJECTED / REVISION_REQUESTED` workflow.
- Build Reviewer Inbox with comments, rejection reasons, and revision requests.
- Enforce strict Approval Gate verifying current `content_revision_id`, `content_sha256`, completed review match, role permissions, and blocking rules.
- Implement append-only `AuditLog` recording actor, organisation, action, target resource, timestamp, and version deltas.

---

## Phase 9 — Analytics and Integration
### Objectives & Completion Criteria
- Build Analytics and Reports UI driven strictly by real database aggregations (compliance trends, violation & severity distributions, approval rates).
- Support report export.
- Verify end-to-end reference scenario (`"The best coffee in Punjab, now only ₹99!"` → detect ₹99 mismatch vs ₹129, unsupported superlative claim, missing `"Terms and conditions apply."` disclaimer → suggest `"Enjoy our Premium Coffee for ₹129. Terms and conditions apply."` → edit → re-review → approve with SHA-256 binding).

---

## Phase 10 — Security, Quality and Deployment
### Objectives & Completion Criteria
- Conduct cross-tenant isolation and RBAC penetration tests.
- Verify rate limiting, safe error envelopes, file upload hardening, and environment secret hygiene.
- Complete automated backend and frontend test suites.
- Finalise production Docker Compose setup and comprehensive operational documentation.
