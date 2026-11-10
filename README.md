# Inkloom AI

**AI-Powered Brand Compliance & Marketing Content Review Platform**
*Built for CodeTitans India 2026 - Round 2*

---

## 1. Problem Statement & Overview

Enterprise marketing and communications teams operate under strict regulatory, legal, and brand identity constraints. In financial services, healthcare, and retail banking, marketing copy containing prohibited guarantees, unverified claims, or missing regulatory disclaimers can trigger severe regulatory penalties and brand erosion.

Traditional compliance reviews suffer from:
1. **Manual Bottlenecks**: Human legal and brand compliance teams spend hours cross-referencing brand books, style guides, and legal disclaimers.
2. **Hallucination Risk in Generic AI**: General-purpose LLMs routinely invent citations, misquote policies, or approve non-compliant marketing claims.
3. **Auditability Deficits**: Lack of traceable verification connecting approved content to the exact text revision reviewed.

**Inkloom AI** addresses this through:
- **Versioned Brand Knowledge Bases (Brand Hub)**: Immutably versioned brand guidelines, compliance rules, and approved brand facts with multi-stage publishing gates.
- **Deterministic Compliance Rule Engine**: High-fidelity pattern and regex evaluation for prohibited terms, mandatory disclaimers, and terminology rules with automated suggested replacements.
- **11-Stage Compliance Orchestration Pipeline**: A staged workflow architecture separating ingestion, deterministic validation, claim extraction, retrieval abstraction, fact checking, unverified guarding, scoring, and remediation.
- **Strict Evidence Grounding & Unverified Guard**: When claims cannot be grounded in approved facts or guideline chunks, they are explicitly tagged `UNVERIFIED` rather than fabricating citations.
- **Governed Human Approval Lifecycle**: Content submissions track parent revision lineages, reviewer assignments, decision states (Pending Review, Under Review, Approved, Rejected, Changes Requested), and audit trails.

---

## 2. System Architecture

```mermaid
flowchart TD
    subgraph Input["Content Input"]
        Raw["Marketing Copy / Multimodal Upload"]
    end

    subgraph Pipeline["11-Stage Compliance Orchestration Pipeline"]
        Ingest["1. Ingest & Normalize Text"]
        Det["2. Deterministic Rule Engine\n(Prohibited Terms, Disclaimers, Terminology)"]
        Extract["3. Claim Extractor"]
        Retrieve["4. Vector Retrieval Abstraction\n(pgvector Schema / Cosine Similarity)"]
        Fact["5. Fact Verifier"]
        Tone["6. Tone Auditor"]
        Guard["7. Unverified Claim Guard\n(Flags Ungrounded Claims)"]
        Score["8. Deduplicate & 0-100 Score Calculation\n(Passing Threshold: >= 70)"]
        Remed["9. Remediation Generator"]
        Schema["10. Schema Validator"]
        Synth["11. Final Synthesis"]

        Ingest --> Det
        Det --> Extract
        Extract --> Retrieve
        Retrieve --> Fact
        Fact --> Tone
        Tone --> Guard
        Guard --> Score
        Score --> Remed
        Remed --> Schema
        Schema --> Synth
    end

    subgraph UI["Compliance Review Workbench"]
        WB["Interactive Review Interface\n- Monospace Character Span Highlights\n- Rule Violation Breakdown & Severity\n- Suggested Replacements & Revision Diff"]
    end

    subgraph Governance["Human Approval Workflow"]
        Sub["Content Submission & Revision Lineage"]
        Appr["Reviewer Action Center\n(Approve / Reject / Request Changes)"]
        Sub --> Appr
    end

    Raw --> Ingest
    Synth --> WB
    WB --> Sub
```

---

## 3. Technology Stack

### Backend
- **Framework**: FastAPI (Python 3.11+ / 3.13) with asynchronous request handlers.
- **Database & ORM**: PostgreSQL 16 with `pgvector` extension; SQLAlchemy 2.0 (mapped models) and Alembic (schema migrations).
- **Security & Auth**: Argon2id (`argon2-cffi`) password hashing, `HS256` JWT authentication with sliding-window rate limiting and immediate token revocation (`jti`).
- **Document Processing**: `pypdf` (PDF extraction), `python-docx` (DOCX extraction), `Pillow` (image preprocessing).
- **Compliance Workflow**: 11-stage compliance orchestration pipeline with deterministic scoring, rule-based auto-corrections, and an Unverified Guard for ungrounded claims.
- **Vector Retrieval Abstraction**: 1024-dimensional vector retrieval schema and cosine similarity abstractions on PostgreSQL `pgvector` (validated via deterministic vector test suites; production embedding API keys not configured).

### Frontend
- **Framework**: React 18 with TypeScript.
- **Build Tool**: Vite.
- **Styling**: Tailwind CSS with enterprise UI tokens.
- **Icons**: Lucide React.
- **Routing & State**: React Router v6, Context-based Authentication and Organisation workspace management.

---

## 4. Prerequisites

| Tool | Recommended Version | Workspace Status |
| :--- | :--- | :--- |
| **Node.js** | `>= 20.x` | `v24.20.0` (Installed) |
| **npm** | `>= 10.x` | `11.19.0` (Installed) |
| **Python** | `>= 3.11` | `3.13.7` (Installed) |
| **Git** | `>= 2.40` | `2.56.0` (Installed) |
| **PostgreSQL** | `16` with `pgvector` | Running on `127.0.0.1:5432` |

---

## 5. Environment Configuration

Copy the template `.env.example` file to create your local `.env`:

```powershell
Copy-Item .env.example .env
```

Generate a secure 64-character random key for `SECRET_KEY`:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Configure key `.env` parameters (never commit `.env` to version control):

| Variable | Description | Default / Example Value |
| :--- | :--- | :--- |
| `SECRET_KEY` | Cryptographic secret for signing JWTs (min 32 chars) | Generated random hex string |
| `JWT_ISSUER` | JWT issuer claim | `inkloom-ai-api` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifespan | `1440` (24 hours) |
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+psycopg://username:password@localhost:5432/inkloom_db` |
| `ALLOW_SQLITE_DEV_FALLBACK` | Permitted for offline unit tests only | `false` |
| `LLM_PROVIDER` | Language model provider selector | `offline` (unconfigured) |
| `EMBEDDING_PROVIDER` | Embedding provider selector | `offline` (unconfigured) |

> **Security Guardrail:** Application startup fails immediately if `SECRET_KEY` is missing, shorter than 32 characters, or left as the template default.

---

## 6. Installation & Startup

### A. Database Migrations
Run Alembic migrations from the `backend/` directory:

```powershell
cd backend
$env:PYTHONPATH = "."
.\.venv-sqlalchemy-test\Scripts\python.exe -m alembic upgrade head
```

### B. Backend API Startup
Start the FastAPI application on `http://127.0.0.1:8000`:

```powershell
cd backend
$env:PYTHONPATH = "."
.\.venv-sqlalchemy-test\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- **Interactive API Documentation (Swagger UI)**: `http://127.0.0.1:8000/docs`
- **Root Health Check**: `http://127.0.0.1:8000/health`
- **Versioned API Health**: `http://127.0.0.1:8000/api/v1/health`

### C. Frontend Development Server
Start Vite on `http://127.0.0.1:5173`:

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

- **Web Application URL**: `http://127.0.0.1:5173`

---

## 7. Demonstration Walkthrough (Seeded Demo Workspace)

The prototype includes an idempotent seeding script (`backend/app/scripts/seed_demo.py`) that provisions a demonstration workspace:
- **Organisation**: `Acme Financial Demo`
- **Admin User**: `judge@inkloom.ai`
- **Published Brand Kit**: `Acme Retail Banking Kit` (v1 PUBLISHED)
- **Active Compliance Rules**:
  1. `BAN-GR` (CRITICAL): Prohibited term "guaranteed returns", suggested replacement "potential returns"
  2. `BAN-RF` (CRITICAL): Prohibited term "risk-free", suggested replacement "lower-risk"
  3. `DISC-RISK` (HIGH): Mandatory disclaimer requirement for market risk statements
  4. `TERM-BRAND` (LOW): Mandatory terminology enforcement for the "Acme" brand name

> **Note on Seeded Data Scope**: The seeded demo kit contains structured compliance rules and brand identity guidelines. It does not contain pre-uploaded guideline document chunks or external semantic embeddings. Consequently, the demo exercises the live deterministic rule engine, scoring, highlighted text spans, auto-corrections, and the Unverified Guard.

### Step 1: Sign In & Verify Organisation Context
1. Open `http://127.0.0.1:5173` in your browser.
2. Log in using an authorized account (`judge@inkloom.ai` or your registered admin user).
3. Confirm that the active organisation selector in the sidebar is set to **Acme Financial Demo**.

### Step 2: Inspect Brand Hub Assets
1. Navigate to **Brand Hub** (`/brand-hub`) via the sidebar.
2. View the published **Acme Retail Banking Kit** (Version 1).
3. Inspect the four active compliance rules (`BAN-GR`, `BAN-RF`, `DISC-RISK`, `TERM-BRAND`) and brand vocabulary settings.

### Step 3: Run Compliance Review
1. Navigate to **Compliance Review** (`/compliance-review`).
2. Select **Acme Retail Banking Kit** and version `v1 (PUBLISHED)`.
3. Choose one of the sample presets or enter marketing copy:
   - Click **Load Banned Term Sample**: Inserts text with prohibited financial guarantees (`"Our High-Yield Savings Account offers guaranteed returns of 12% annually..."`).
   - Click **Load Hybrid RAG Sample**: Inserts text with marketing claims.
4. Click **Run Compliance Review**.
5. Observe the execution results:
   - **Compliance Score**: Calculated on a 0 to 100 scale (passing threshold: >= 70).
   - **Status Badge**: Flags `NON_COMPLIANT` (score < 70) or `COMPLIANT` (score >= 70).
   - **Violations & Rule Breakdown**: Displays violated rule codes, severity badges (`HIGH`, `MEDIUM`, `LOW`), and category descriptions.
   - **Highlighted Text**: Exact character spans are rendered in monospace with visual violation highlights.

### Step 4: Inspect Evidence & Grounding
1. Observe the **Evidence & Source Citations** section.
2. **Unverified Claim Guard in Action**: Because external semantic embeddings and document chunks are not pre-seeded for this kit, factual claims lacking verified backing are flagged with `UNVERIFIED` status rather than fabricating non-existent citations.

### Step 5: Apply Corrections & Inspect Diff
1. In the **Suggested Corrections** card, view the recommended compliant replacements.
2. Click **Apply Suggested Corrections** to patch the draft text automatically.
3. Review the visual revision comparison diff showing original vs. corrected copy.
4. Re-run compliance review to verify the score improves to passing status.

### Step 6: Submit for Human Approval
1. In the **Submit for Approval** section, enter optional submitter notes.
2. Click **Submit for Approval**.
3. A content submission record is created in `PENDING_REVIEW` status, linked to its revision lineage.

### Step 7: Reviewer Sign-Off in Approvals Queue
1. Navigate to **Approvals** (`/approvals`).
2. Select the pending submission.
3. Review submission details, revision number, and submission history audit trail.
4. As an authorized reviewer, click **Approve**, **Reject**, or **Request Changes** with reviewer comments.
5. The submission transitions to `APPROVED`, completing the review workflow.

---

## 8. Implementation Status: Implemented vs. Planned

| Capability / Phase | Status | Details |
| :--- | :---: | :--- |
| **Phase 1: Foundation & Architecture** | **Implemented** | FastAPI asynchronous backend, PostgreSQL + `pgvector`, React + Vite frontend, multi-tenant isolation. |
| **Phase 2: Auth, RBAC & Isolation** | **Implemented** | Argon2id hashing, `HS256` JWT with `jti` revocation, multi-tenant isolation, last-admin protection, granular permissions. |
| **Phase 3: Brand Hub & Versioning** | **Implemented** | Brand Kits, immutable published versions, compliance rules, approved facts, pre-publish validation gates. |
| **Phase 4: Deterministic Rule Engine** | **Implemented** | Regex/pattern violation detection, auto-correction generation, content revision lineages, human approval lifecycle. |
| **Phase 5: Multimodal Document Ingestion** | **Implemented** | PDF, DOCX, and image file parsing, MIME validation, SHA-256 file hashing, content submission tracking. |
| **Phase 6.1: Guideline Ingestion & Chunking** | **Implemented** | Guideline document upload, token-aware chunking, overlap preservation, heading hierarchy extraction. |
| **Phase 6.2: Vector Retrieval Abstraction** | **Implemented (Offline)** | 1024-dim `pgvector` indexing and cosine similarity retrieval abstractions implemented and tested offline; live production embedding generation is unconfigured. |
| **Phase 6.3: Compliance Orchestration Workflow** | **Implemented** | 11-stage compliance execution pipeline, evidence validation, unverified guard, deterministic score preservation. |
| **Phase 6.4: Review Workbench & UI** | **Implemented** | Interactive compliance workbench, monospace span highlights, rule breakdown, corrections diff, approvals integration. |
| **Phase 7: Integrated Content Editor** | *Planned* | In-browser WYSIWYG rich text editor with live inline violation spans and real-time re-scoring. |
| **Phase 8: Unified Audit Logging** | *Planned* | Centralized append-only security audit log ledger (submissions currently maintain revision lineages and review action records). |
| **Phase 9: Enterprise Analytics & Export** | *Planned* | Aggregated compliance trend dashboards, cross-department violation metrics, and PDF/CSV compliance export reports. |

---

## 9. Engineering Disclosures & Fallback Modes

To maintain full transparency:

1. **LLM Credentials & Semantic Embedding Configuration**:
   - Production API credentials for third-party LLMs (e.g. `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) and production embedding APIs (e.g. `VOYAGE_API_KEY`) are **not configured** in this environment.
   - The platform operates in **Deterministic Fallback mode** (`engine_mode = "DETERMINISTIC_FALLBACK"`). In this mode, the system executes deterministic compliance rules, extracts verified evidence, activates the Unverified Claim Guard, and calculates authoritative 0 to 100 scores without external API dependencies or risk of third-party downtime.
2. **LangGraph Runtime**:
   - The backend compliance pipeline implements an **11-stage compliance orchestration workflow** with explicit state management, unverified claim guarding, and deterministic score preservation. It does not bundle or depend on the external `langgraph` package at runtime.
3. **Security Audit Logging**:
   - Individual content submissions track parent revision lineages and review action timestamps.
   - A **centralized, append-only security audit ledger** across all administrative events is **planned for Phase 8** and is not currently implemented.
4. **Mock Embeddings in Offline Testing**:
   - Unit tests utilize standardized 1024-dimensional normalized vectors to validate vector search schema and tenant-isolation retrieval without incurring external network latency.

---

## 10. Automated Testing

Commands to run the automated test suite and frontend verification:

```powershell
# Run backend test suite
cd backend
$env:PYTHONPATH = "."
.\.venv-sqlalchemy-test\Scripts\python.exe -m pytest -v
```

```powershell
# Verify frontend TypeScript compilation and production bundle build
cd frontend
npm run lint
npm run build
```

---

## 11. Project Team

Developed for **CodeTitans India 2026 - Round 2** by:

- **Pathik Talwar** - Backend Architecture, Infrastructure, Deterministic Compliance Engine & AI Systems
- **Pragati Kumari** - Frontend Architecture, User Interface, Brand Hub & Compliance Review Workbench
