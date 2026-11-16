# Inkloom AI

**Enterprise Brand Compliance & Human-Gated Approval Engine**<br/>
*Built for CodeTitans India 2026 — Round 3 Finalist Submission*<br/>
*Team: TITANIUM*<br/>
*Authors: Pragati Kumari & Pathik Talwar*

[![Python Version](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18.3-61dafb.svg)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178c6.svg)](https://www.typescriptlang.org/)
[![Tailwind CSS](https://img.shields.io/badge/TailwindCSS-3.4-38bdf8.svg)](https://tailwindcss.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-336791.svg)](https://github.com/pgvector/pgvector)
[![License](https://img.shields.io/badge/license-Proprietary%20%2F%20Educational-lightgrey.svg)]()

---

## Table of Contents

- [1. Executive Summary](#1-executive-summary)
- [2. Problem Statement](#2-problem-statement)
- [3. The Inkloom AI Solution](#3-the-inkloom-ai-solution)
- [4. Target Users & Use Cases](#4-target-users--use-cases)
- [5. Key Features & Capabilities](#5-key-features--capabilities)
- [6. System Architecture & Workflows](#6-system-architecture--workflows)
- [7. Technology Stack](#7-technology-stack)
- [8. Repository Structure](#8-repository-structure)
- [9. Prerequisites & System Requirements](#9-prerequisites--system-requirements)
- [10. Local Installation & Setup](#10-local-installation--setup)
- [11. Environment Variables Configuration](#11-environment-variables-configuration)
- [12. PostgreSQL 16 & pgvector Setup](#12-postgresql-16--pgvector-setup)
- [13. Running Backend, Frontend & Docker Stack](#13-running-backend-frontend--docker-stack)
- [14. Brand Hub & Multimodal Guideline Ingestion](#14-brand-hub--multimodal-guideline-ingestion)
- [15. Compliance Review & Evidence-Linked Findings](#15-compliance-review--evidence-linked-findings)
- [16. 1-Click Remediation & Revision Lineage](#16-1-click-remediation--revision-lineage)
- [17. Independent Reviewer & Dual-Control Maker-Checker](#17-independent-reviewer--dual-control-maker-checker)
- [18. Immutable Audit Trail & Defense-in-Depth Security](#18-immutable-audit-trail--defense-in-depth-security)
- [19. Automated Testing & Verification Results](#19-automated-testing--verification-results)
- [20. Submission Evidence & Screenshots](#20-submission-evidence--screenshots)
- [21. 5-Minute Evaluation Walkthrough for Judges](#21-5-minute-evaluation-walkthrough-for-judges)
- [22. Transparent Limitations & Engineering Disclosures](#22-transparent-limitations--engineering-disclosures)
- [23. Team TITANIUM & Individual Contributions](#23-team-titanium--individual-contributions)
- [24. Acknowledgements & Hackathon Notice](#24-acknowledgements--hackathon-notice)

---

## 1. Executive Summary

**Inkloom AI** is an enterprise-grade brand compliance, regulatory risk prevention, and human-gated approval platform engineered for heavily regulated industries such as retail banking, wealth management, insurance, and healthcare.

Unlike generic large language model wrappers that produce hallucinated citations and inconsistent rulings, Inkloom AI combines an **authoritative, deterministic compliance engine** with cryptographic version-locking, monospace character-level violation pinpointing, 1-click automated remediation diffs, and strict **Maker-Checker dual-control governance**.

Every marketing claim is evaluated against an organisation's immutable Brand Kit rules. Non-compliant collateral is halted before publication, remediated into clean revisions with full parent-child lineage, and submitted to independent compliance officers whose decisions and comments are permanently recorded in an append-only PostgreSQL ledger.

---

## 2. Problem Statement

Enterprises operating in regulated markets face four existential challenges when creating and distributing marketing communications:

1. **Statutory Penalties & Brand Erosion**: An unsubstantiated return claim (e.g. *"guaranteed 12% returns"*), an unlawful risk statement (e.g. *"completely risk-free investment"*), or an omitted statutory disclaimer triggers immediate regulatory fines from authorities such as SEBI, FTC, and FCA, accompanied by reputational brand damage.
2. **Review Bottlenecks & Manual Fatigue**: Brand governance and legal compliance teams manually review hundreds of marketing drafts against multi-page PDF guidelines, brand voice documents, and spreadsheet rule-lists, creating multi-week campaign deployment delays.
3. **Generative AI Hallucination & Fabrication Risk**: Generic AI models frequently hallucinate regulatory clauses, fail to detect nuanced wording violations, and invent phantom policy citations.
4. **Broken Auditability & Lack of Dual Control**: Marketing reviews conducted over ad-hoc email threads and chat messages fail regulatory audits due to the absence of cryptographic integrity hashes, immutable action logging, and enforced separation between authors and approvers.

---

## 3. The Inkloom AI Solution

Inkloom AI resolves these challenges through a governed, deterministic-first verification lifecycle:

- **Immutable Brand Hub**: Brand Kits, approved facts, and compliance rules are versioned and cryptographically locked. Once published, database triggers guarantee that active standards cannot be silently modified.
- **Authoritative Deterministic Engine**: High-speed, ReDoS-protected regex and AST pattern matching evaluate copy with mathematical precision, returning reproducible scores from $0$ to $100$.
- **Exact Character-Span Pinpointing**: Flagged violations cite exact character coordinates (`char_start`, `char_end`), rendering visual highlights over the problematic phrases.
- **1-Click Auto-Remediation & Revision Lineage**: Non-overlapping replacements generate a compliant child revision (Revision 2) with an interactive before/after diff viewer, preserving complete historical lineage without overwriting original drafts.
- **Maker-Checker Dual Control**: Strict defense-in-depth controls prevent authors from approving their own copy or assigning themselves as reviewers. Independent reviewers inspect violations and issue formal `APPROVE`, `REJECT`, or `REQUEST_CHANGES` decisions.
- **Append-Only Database Audit Ledger**: All actions — uploads, evaluations, assignments, comments, and decisions — are committed to an immutable ledger protected by PostgreSQL triggers.

---

## 4. Target Users & Use Cases

| User Persona | Role & Objectives | How Inkloom AI Empowers Them |
| :--- | :--- | :--- |
| **Marketing Content Authors** | Create campaign copy, social banners, and promotional collateral. | Real-time compliance feedback, pinpointed violation spans, 1-click auto-fixes, and transparent scoring ($0 \rightarrow 100$). |
| **Brand Managers** | Establish corporate brand guidelines, visual identity, and voice rules. | Version-locked Brand Hub, multi-format guideline ingestion (PDF, TXT, DOCX, PNG/OCR), and approved fact management. |
| **Compliance & Legal Officers** | Verify statutory disclaimers, enforce regulatory prohibitions, prevent fines. | Centralized Approvals Queue (`/approvals`), revision diff comparison, independent decision recording, and non-repudiation audit trails. |
| **Enterprise Executives & Auditors** | Monitor organisational risk, ensure governance, prepare audit filings. | Real-time telemetry dashboard (`/`), immutable database audit logs (`brand_audit_logs`), and cryptographic content hashes. |

---

## 5. Key Features & Capabilities

### Brand Hub & Version Governance
- **Version Lifecycle State Machine**: Brand Kits progress through `DRAFT` $\rightarrow$ `PUBLISHED` $\rightarrow$ `ARCHIVED`.
- **Single-Draft & Single-Published Invariant**: Enforced by database partial unique indexes.
- **Database Trigger Immutability**: Active published versions cannot be modified, re-parented, or deleted.
- **Multimodal Guideline Ingestion**: Secure ingestion of `.pdf`, `.docx`, `.txt`, `.png`, and `.jpeg` brand documentation.
- **Sentence-Aware Token Chunking**: Chunks documents into 512-token segments with 64-token sliding window overlap and hierarchical heading extraction.

### Authoritative Deterministic Compliance Engine
- **Pattern Match Modes**: `EXACT`, `CASE_INSENSITIVE`, `WORD_BOUNDARY`, and ReDoS-protected `REGEX`.
- **Character Offset Indexing**: Monospace visual highlights rendered over flagged violations.
- **Weighted Severity Scoring**: Transparent penalty deduction:
  $$\text{Score} = \max\left(0, 100 - \sum \text{Penalties}\right)$$
  - `CRITICAL`: -40 points per violation
  - `HIGH`: -20 points per violation
  - `MEDIUM`: -10 points per violation
  - `LOW`: -5 points per violation
- **Pass / Fail Threshold**: Minimum score of $\ge 70$ required to qualify for compliance approval.

### Remediation & Governance
- **1-Click Suggested Corrections**: Automated computation of non-overlapping string replacements.
- **Revision Lineage Tracking**: Spawns sequential child revisions (`parent_submission_id = sub.id`), resetting approvals and maintaining complete audit lineage.
- **Visual Before / After Diff Viewer**: 24-line unified diff rendering modified and added spans.
- **Dual-Control Maker-Checker**: Backend HTTP 403 halt if an author attempts to approve their own submission; HTTP 400 halt on self-assignment.
- **Terminal State Lock**: Decisions on `APPROVED` or `REJECTED` copy locked with HTTP 409 Conflict.
- **Append-Only Audit Trail**: PostgreSQL trigger prevents `UPDATE` and `DELETE` on `brand_audit_logs`.

---

## 6. System Architecture & Workflows

### 6.1 High-Level Architecture Topology

```
                         [ Public Internet / Evaluator Browser ]
                                            │
                                            ▼
                    ┌───────────────────────────────────────────────┐
                    │      React SPA / Frontend (Vite, Port 5173)   │
                    │      ChatGPT-Inspired Dark Theme (#212121)    │
                    │                                               │
                    │  • AuthProvider (Argon2id / HS256 JWT)        │
                    │  • Live Telemetry Dashboard (/)               │
                    │  • Brand Hub & Guidelines (/brand-hub)        │
                    │  • Compliance Review (/compliance-review)     │
                    │  • Approvals & Reviewer Queue (/approvals)    │
                    └───────────────────────┬───────────────────────┘
                                            │ HTTPS / Bearer JWT
                                            ▼
                    ┌───────────────────────────────────────────────┐
                    │      FastAPI REST API Backend (Port 8000)     │
                    │                                               │
                    │  • Multi-Tenant RBAC Middleware               │
                    │  • Deterministic Compliance Engine            │
                    │  • 11-Stage Orchestration Pipeline            │
                    │  • Multimodal Extraction (pypdf, Pillow, OCR) │
                    │  • Human Approval Service (Maker-Checker)     │
                    └───────────────────────┬───────────────────────┘
                                            │ Connection Pool
                                            ▼
                    ┌───────────────────────────────────────────────┐
                    │     PostgreSQL 16 + pgvector (Port 5432)      │
                    │                                               │
                    │  • Relational Schema (Alembic 0001–0007)      │
                    │  • pgvector Column (vector(1024))             │
                    │  • Immutability & Single-Published Triggers   │
                    │  • Append-Only Audit Trigger (fn_audit_logs)  │
                    └───────────────────────────────────────────────┘
```

### 6.2 Maker-Checker Dual-Control Lifecycle

```
       [ Submitter: judge@inkloom.ai ]
                      │
                      ▼
          Creates Revision 1 (Score 0)
                      │
      ┌───────────────┴───────────────┐
      │ Self-Approve Attempt          │ Submits for Approval
      ▼                               ▼
[ HTTP 403 Forbidden ]     [ Reviewer Assigned ]
 "Author cannot approve                   │
   own submission"                        ▼
                         [ independent_reviewer@inkloom.ai ]
                                          │
                                          ▼
                               Inspects 4 Violations
                                          │
                                          ▼
                               Executes REJECT Decision
                                          │
                                          ▼
                               [ Status: REJECTED (Locked) ]
                               (Mutations return HTTP 409)
                                          │
                                          ▼
                            Author Applies 1-Click Suggestions
                                          │
                                          ▼
                             Creates Revision 2 (Score 100)
                                          │
                                          ▼
                         [ independent_reviewer@inkloom.ai ]
                                          │
                                          ▼
                               Executes APPROVE Decision
                                          │
                                          ▼
                               [ Status: APPROVED (Locked) ]
```

---

## 7. Technology Stack

| Layer | Technology | Version | Purpose |
| :--- | :--- | :---: | :--- |
| **Frontend Framework** | React | 18.3 | Reactive single-page component architecture |
| **Language** | TypeScript | 5.6 | Strict static type safety (zero `any`, 0 type errors) |
| **Build & Dev Server** | Vite | 5.4 | Fast HMR dev server and optimized production bundler |
| **Styling & Theme** | Tailwind CSS | 3.4 | ChatGPT-inspired dark palette (`#212121`, `#171717`, `#10A37F`) |
| **Icons** | Lucide React | 0.460+ | Modern, accessible enterprise iconography |
| **Backend Framework** | FastAPI | 0.115+ | High-performance asynchronous Python ASGI REST API |
| **Backend Language** | Python | 3.12 / 3.13 | Type-hinted asynchronous application runtime |
| **Data Validation** | Pydantic | 2.10+ | Strict request/response serialization & validation |
| **Database ORM** | SQLAlchemy | 2.0 | Asynchronous-ready relational modeling & session pooling |
| **Database Migrations**| Alembic | 1.14+ | Versioned relational migrations (0001 through 0007) |
| **Database Engine** | PostgreSQL | 16 | ACID-compliant relational data store with immutability triggers |
| **Vector Extension** | pgvector | 0.8+ | 1024-dimensional vector embedding storage & cosine distance (`<=>`) |
| **Document Processing**| pypdf, python-docx | Latest | Secure text extraction from PDF and DOCX files |
| **Image & OCR** | Pillow, pytesseract | Latest | MIME validation, decompression bomb guards, and OCR text extraction |
| **Security & Auth** | Passlib (Argon2id), PyJWT | Latest | Password hashing, signed JWT tokens, and JTI revocation |
| **Containerization** | Docker & Docker Compose | Latest | Multi-stage production container topology and service health checks |

---

## 8. Repository Structure

```
Inkloom-AI/
├── backend/
│   ├── alembic/                      # Alembic migration scripts (0001–0007)
│   ├── app/
│   │   ├── api/
│   │   │   ├── routes/               # Modular REST endpoints (auth, brand_kits, compliance, health)
│   │   │   └── deps.py               # Dependency injection & RBAC security checks
│   │   ├── core/                     # Configuration, security, rate limiting, and database engine
│   │   ├── models/                   # SQLAlchemy ORM models (BrandKit, Submission, AuditLog)
│   │   ├── schemas/                  # Pydantic validation schemas
│   │   └── services/                 # Business logic: compliance_engine, guideline_document_service
│   │       └── ai_workflow/          # 11-stage compliance pipeline & unverified claim guard
│   ├── tests/                        # Comprehensive test suites (auth, rbac, ocr, approvals)
│   ├── Dockerfile                    # Production Python 3.12 container with Tesseract OCR
│   ├── entrypoint.sh                 # Database migration & service bootloader
│   └── requirements.txt              # Production Python dependencies
├── frontend/
│   ├── src/
│   │   ├── components/               # UI components (GuidelineDocumentsManager, StatusBadge)
│   │   ├── layouts/                  # AppLayout with ChatGPT-inspired dark sidebar
│   │   ├── pages/                    # Views: LoginPage, DashboardHome, BrandRulesPage, ApprovalsPage
│   │   ├── services/                 # Axios/Fetch API client modules
│   │   └── types/                    # TypeScript interfaces & domain models
│   ├── tests/                        # Node test runner unit tests (GuidelineDocumentsManager)
│   ├── Dockerfile                    # Multi-stage Nginx production container
│   ├── nginx.conf                    # Reverse proxy, caching, and SPA fallback rules
│   └── package.json                  # Frontend dependencies and npm scripts
├── ROUND3_SUBMISSION_EVIDENCE/       # 11 verified application screenshots with unique SHA-256 hashes
├── ROUND3_JUDGE_DEMO_SCRIPT.md       # 5-minute interactive presentation script for evaluators
├── ROUND3_FINAL_SUBMISSION_CHECKLIST.md # Complete verification checklist
├── docker-compose.yml                # Local dev PostgreSQL 16 + pgvector setup
├── docker-compose.prod.yml           # Production multi-container deployment stack
└── README.md                         # Comprehensive project documentation
```

---

## 9. Prerequisites & System Requirements

- **Operating System**: Linux (Ubuntu 22.04+ recommended), macOS 13+, or Windows 11 with WSL2 / PowerShell.
- **Node.js**: `v20.x` or `v22.x` LTS (with `npm 10+`).
- **Python**: `3.12.x` or `3.13.x`.
- **Database**: PostgreSQL `16.x` with `pgvector` extension enabled.
- **Docker**: Docker Engine `24.x+` with Docker Compose `v2.x+` (recommended for instant setup).
- **OCR Engine (Optional for host, packaged in Docker)**: `tesseract-ocr` and `tesseract-ocr-eng`.

---

## 10. Local Installation & Setup

### 10.1 Clone the Repository
```bash
git clone https://github.com/Pathik008/Inkloom-AI.git
cd Inkloom-AI
```

### 10.2 Backend Setup
```bash
cd backend

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 10.3 Frontend Setup
```bash
cd ../frontend

# Install dependencies
npm ci
```

---

## 11. Environment Variables Configuration

Copy the provided template `.env.example` to `.env` in the project root:

```bash
cp .env.example .env
```

### Required Configuration Values
```ini
# Application Environment
APP_ENV=development
DEBUG=false
SECRET_KEY="GENERATE_A_STRONG_RANDOM_HEX_SECRET_AT_LEAST_32_CHARACTERS"

# PostgreSQL 16 + pgvector Connection
POSTGRES_USER="inkloom_user"
POSTGRES_PASSWORD="YOUR_SECURE_DATABASE_PASSWORD"
POSTGRES_DB="inkloom_db"
POSTGRES_HOST="localhost"
POSTGRES_PORT=5432
DATABASE_URL="postgresql+psycopg://inkloom_user:YOUR_SECURE_DATABASE_PASSWORD@localhost:5432/inkloom_db"

# CORS Configuration
CORS_ORIGINS="http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"

# Frontend API Target
VITE_API_BASE_URL="http://localhost:8000"

# Demonstration Password Configuration (for offline seeding)
DEMO_ADMIN_PASSWORD="YOUR_DEMO_ADMIN_PASSWORD"
```

> [!SECURITY]
> **Credential Protection Policy**: Active demonstration passwords and production credentials must **never** be committed to public repositories. Hackathon judge credentials are provided privately to evaluators.

---

## 12. PostgreSQL 16 & pgvector Setup

Inkloom AI requires PostgreSQL 16 with the `pgvector` extension. The easiest way to provision the database is using Docker:

```bash
docker run --name inkloom-postgres-pgvector \
  -e POSTGRES_USER=inkloom_user \
  -e POSTGRES_PASSWORD=YOUR_SECURE_DATABASE_PASSWORD \
  -e POSTGRES_DB=inkloom_db \
  -p 5432:5432 \
  -d pgvector/pgvector:pg16
```

### Run Database Migrations
```bash
cd backend
alembic upgrade head
```

---

## 13. Running Backend, Frontend & Docker Stack

### 13.1 Run Backend Development Server
```bash
cd backend
# Windows PowerShell:
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
# Linux / macOS:
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
- Health Check: `http://127.0.0.1:8000/health`
- Interactive OpenAPI Docs: `http://127.0.0.1:8000/docs`

### 13.2 Run Frontend Development Server
```bash
cd frontend
npm run dev -- --host 0.0.0.0 --port 5173
```
- Web Application: `http://127.0.0.1:5173`

### 13.3 Run Full Production Stack with Docker Compose
```bash
docker compose -f docker-compose.prod.yml up -d --build
```
- Frontend Application: `http://localhost:80`
- Frontend Health Probe: `http://localhost:80/healthz`
- Backend API Proxy: `http://localhost:80/api/v1/`

---

## 14. Brand Hub & Multimodal Guideline Ingestion

Navigate to `/brand-hub` to manage Brand Kits and regulatory standards:

- **Immutable Published Kit (`v1.0.0`)**: In the **Acme Financial Demo** organisation, the active kit contains 4 regulatory rules:
  1. `BAN-GR` (Critical): Prohibition of guaranteed returns promises.
  2. `BAN-RF` (Critical): Prohibition of risk-free claims.
  3. `DISC-RISK` (High): Mandatory statutory market risk disclaimer.
  4. `TERM-BRAND` (Low): Corporate wordmark requirement.
- **Multimodal Guideline Ingestion (Draft `v2`)**: To update standards, teams provision Draft versions that ingest guidelines across formats:
  - **PDF Documents**: Parsed via `pypdf`, chunked with 512-token windows and heading extraction.
  - **TXT Files**: Parsed directly with encoding detection and paragraph segmenting.
  - **Images & Visual Guides (PNG/JPG)**: Extracted via OCR with decompression bomb protection.

---

## 15. Compliance Review & Evidence-Linked Findings

Navigate to `/compliance-review` to inspect evaluation copy:

- **Evaluation Copy (Revision 1)**: Score **`0 / 100 — FAIL`**.
- **Monospace Span Highlighting**: Pinpoints exact character offsets:
  - Span `1511–1529`: Flags `"guaranteed returns"` (Penalty: -40).
  - Span `1688–1697`: Flags `"risk-free"` (Penalty: -40).
  - Span `3080–3089`: Flags `"risk-free"` (Penalty: -40).
  - Document-Level: Flags missing mandatory market risk disclaimer (Penalty: -20).
- **Penalty Calculation**: $100 - (40 + 40 + 40 + 20) = -40 \rightarrow$ clamped to **0 / 100**.

---

## 16. 1-Click Remediation & Revision Lineage

1. In the Compliance Workbench, click **Apply 1-Click Suggestions**.
2. The engine computes non-overlapping string replacements:
   - `"guaranteed returns"` $\rightarrow$ `"potential returns"`
   - `"risk-free"` $\rightarrow$ `"lower-risk"`
   - Appends mandatory statutory SEBI disclaimer to document footer.
3. Automatically provisions **Revision 2**:
   - `revision_number`: 2
   - `parent_submission_id`: `701d2e17-25ba-44a5-aba7-41f4a71afd2c`
   - Score: **`100 / 100 — PASS`** (0 remaining violations).
4. Reviewers inspect an interactive **unified diff** showing all 24 changed and added lines.

---

## 17. Independent Reviewer & Dual-Control Maker-Checker

Navigate to `/approvals` as an authorized compliance officer:

- **Maker-Checker Security Enforcement**:
  - The submitter (`judge@inkloom.ai`) cannot self-approve Revision 1 or Revision 2. The backend service layer rejects self-approval with **HTTP 403 Forbidden** (*"Independent review required: Submitter cannot approve their own submission."*).
  - In the frontend UI, decision action buttons are disabled with an amber warning banner.
- **Independent Compliance Reviewer (`independent_reviewer@inkloom.ai`)**:
  - **Revision 1 Decision**: Executed **`REJECT`** with formal commentary: *"Rejected: Marketing copy contains critical regulatory violations (guaranteed returns and risk-free claims) and missing mandatory market risk disclaimer."*
  - **Revision 2 Decision**: Executed **`APPROVE`** with sign-off: *"Approved: All regulatory violations remediated. Mandatory market risk disclaimer present and verified. Meets full compliance requirements."*
- **Terminal State Locking**: Attempts to mutate decided submissions return **HTTP 409 Conflict**.

---

## 18. Immutable Audit Trail & Defense-in-Depth Security

Click **Inspect** $\rightarrow$ **Review Action Log** on `/approvals` or inspect database records:

- **Audit Record Count**: Exactly **31 audit records** committed in PostgreSQL table `brand_audit_logs`.
- **Event Coverage**:
  - Document uploads, chunking, and re-parsing.
  - Rule creation, modification, and approval.
  - Content creation, submission, revision, and reviewer assignment.
  - Comments, rejection, and final approval sign-off.
- **Trigger-Level Non-Repudiation**: Protected by database trigger `trg_validate_and_protect_brand_audit_logs`. Direct SQL `UPDATE` or `DELETE` statements are aborted by PostgreSQL with error `[P0005]: brand_audit_logs are append-only`.

---

## 19. Automated Testing & Verification Results

To maintain complete transparency, test results are documented across execution environments:

| Test Suite / Scope | Execution Environment | Tests | Result | Notes |
| :--- | :--- | :---: | :---: | :--- |
| **Multimodal & OCR Suites** | Docker Container (`inkloom-backend-dev`) | **17** | **17 Passed (100%)** | Validates PNG, JPG, and PDF ingestion with native Tesseract OCR. |
| **Frontend TypeScript Type Check** | Host CLI (`tsc --noEmit`) | — | **0 Errors (100%)** | Strict type safety across all components and pages. |
| **Frontend Unit Tests** | Node Test Runner (`node --test`) | **8** | **8 Passed (100%)** | Validates GuidelineDocumentsManager, MIME validation, and RBAC contracts. |
| **Git Hygiene Check** | Git CLI (`git diff --check`) | — | **0 Errors (100%)** | Clean working tree; zero whitespace errors or merge conflicts. |
| **Host Python Backend Suite** | Windows 11 Host (`.venv`) | **225** | **204 Passed** | 204 passed, 9 skipped, 5 failed (missing host Tesseract binary), 7 errors (destructive Alembic tests). |

> [!NOTE]
> **Host Backend Suite Breakdown**: The 5 host failures occurred solely because the bare Windows host lacks `tesseract.exe` on PATH. When executed inside the Linux Docker container where Tesseract is installed, **all 17 OCR tests pass 100%**. The 7 Alembic errors occurred due to Windows AppControl policy blocking `.venv` C-extensions and safe guards preventing destructive schema drops against the active demo database.

---

## 20. Submission Evidence & Screenshots

All 11 genuine application screenshots in `ROUND3_SUBMISSION_EVIDENCE/` were captured directly from the live application over Chrome DevTools Protocol:

| # | Screenshot Filename | SHA-256 Checksum | Verified Interface & Workflow |
| :---: | :--- | :--- | :--- |
| **01** | `01_login_page.png` | `737c3f39b8fb...` | ChatGPT-inspired dark split-screen with product intro, 5-step workflow, and 5 benefits. |
| **02** | `02_dashboard_overview.png` | `f1599fecc135...` | Live telemetry cards, submission status distribution, and active brand kit summary. |
| **03** | `03_brand_hub_brand_kit.png` | `4d2b79f5f137...` | Acme Financial Demo workspace, Acme Retail Banking Kit v1 (PUBLISHED). |
| **04** | `04_compliance_rules.png` | `910653084cde...` | 4 active immutable compliance rules with severity badges (`BAN-GR`, `BAN-RF`, etc.). |
| **05** | `05_guideline_documents_manager.png` | `ff2fd9a38024...` | Draft v2 Guideline Documents Manager showing ingested PDF, TXT, and PNG assets. |
| **06** | `06_compliance_review_findings.png` | `18dc99945255...` | Revision 1 Workbench: 0/100 FAIL, 4 violations, monospace character span highlights. |
| **07** | `07_remediation_diff_comparison.png` | `f5d9c59f3a22...` | Revision 2 Workbench: 100/100 PASS, unified diff comparison against Revision 1. |
| **08** | `08_approval_inbox_queue.png` | `ed1ea66e9df4...` | Reviewer Approvals Queue displaying Revision 1 (REJECTED) and Revision 2 (APPROVED). |
| **09** | `09_reviewer_rejected_decision.png` | `b46e86d6c202...` | Reviewer decision inspection modal displaying formal rejection reasoning for Revision 1. |
| **10** | `10_reviewer_approved_decision.png` | `9694769d101d...` | Reviewer decision inspection modal displaying approval sign-off for Revision 2. |
| **11** | `11_audit_trail_action_log.png` | `fe32142e00bd...` | Full sequential audit trail and action history with timestamps and user attribution. |

---

## 21. 5-Minute Evaluation Walkthrough for Judges

Refer to [ROUND3_JUDGE_DEMO_SCRIPT.md](file:///c:/Users/Win-11/Desktop/My%20World/ROUND3_JUDGE_DEMO_SCRIPT.md) for the complete presentation narrative:

```
[00:00 - 00:45] Minute 1: Problem, Solution & High-Level Architecture
[00:45 - 01:30] Minute 2: Brand Hub, Immutability & Guideline Ingestion
[01:30 - 02:45] Minute 3: Compliance Analysis, Span Pinpointing & 1-Click Remediation
[02:45 - 04:00] Minute 4: Dual-Control Maker-Checker & Independent Review Decision
[04:00 - 05:00] Minute 5: Immutable Audit Ledger, Technical Differentiators & Wrap-up
```

### Quick URL Reference
- **Frontend Application**: `http://127.0.0.1:5173`
- **Backend Health Check**: `http://127.0.0.1:8000/health`
- **Judge / Submitter Account**: `judge@inkloom.ai` (Password provided privately)
- **Reviewer Account**: `independent_reviewer@inkloom.ai` (Password provided privately)

---

## 22. Transparent Limitations & Engineering Disclosures

To uphold the highest scientific and engineering standards:

1. **Deterministic Rule Engine Is Authoritative**: The deterministic regex/AST compliance engine executes authoritatively without external API latency or hallucination risks.
2. **Third-Party LLM & Embedding Credentials**: External LLM providers (e.g. OpenAI, Anthropic, Gemini) and embedding APIs are unconfigured in the offline demonstration environment. The system operates in **`DETERMINISTIC_FALLBACK`** mode.
3. **Active Unverified Claim Guard**: When external semantic AI models are offline, the system never fabricates hallucinated findings or fake citations (0 false violations generated).
4. **Vector Retrieval Architecture**: The `vector(1024)` PostgreSQL schema with native cosine distance search (`<=>`) is fully implemented and tested with mock embeddings. Live semantic RAG is not claimed as active without configured credentials.

---

## 23. Team TITANIUM & Individual Contributions

Developed for **CodeTitans India 2026** by **Team TITANIUM**:

### Pragati Kumari
*Frontend Architecture, Compliance Review Workbench, Approvals Queue UI & Design System*
- **Compliance Review Workbench**: Designed and built the interactive review interface featuring monospace character span highlights, rule violation breakdowns, 1-click suggested corrections, and revision diff comparisons.
- **Human Approval & Reviewer Action Center**: Built the Approvals Queue UI (`/approvals`) supporting status filtering, maker-checker assignment guards, and review decision modals.
- **Brand Hub & Rules Management**: Built the Brand Kit configuration interface, guideline upload UI, and compliance rule management pages.
- **Live Metrics Dashboard (Phase 5.1)**: Developed the real-time telemetry dashboard with organisation switching resilience, skeleton loaders, and health status indicators.
- **ChatGPT-Inspired Dark Theme**: Architected the modern, distraction-free charcoal and emerald design system.

### Pathik Talwar
*Backend Infrastructure, Deterministic Compliance Engine, RBAC, Database & AI Systems*
- **FastAPI Architecture & REST APIs**: Architected the asynchronous backend, Pydantic v2 schemas, CORS handling, and modular routing structure.
- **PostgreSQL Database & pgvector**: Designed relational schema, Alembic migrations (0001–0007), PostgreSQL immutability triggers, and 1024-dimensional vector indexing.
- **Authentication & Multi-Tenant RBAC**: Implemented Argon2id password hashing, HS256 JWT tokens with database `jti` revocation, multi-tenant data isolation, and cryptographic invitation workflows.
- **Deterministic Compliance Engine**: Engineered pure-function rule evaluation with ReDoS protection, exact span indexing, and non-overlapping auto-fix replacement.
- **Compliance Orchestration & Unverified Guard**: Implemented the 11-stage compliance pipeline, deterministic score preservation, and the unverified claim guard.
- **Multimodal Document Processing**: Built extraction pipelines for PDF (`pypdf`), DOCX (`python-docx`), and image collateral with SHA-256 integrity hashing and OCR fallbacks.
- **DevOps & Production Containerization**: Authored multi-stage Dockerfiles, Nginx reverse proxy templates, and verified deployment configurations.

---

## 24. Acknowledgements & Hackathon Notice

- **Event**: CodeTitans India 2026 — Round 3 Finalist Stage
- **Team**: TITANIUM
- **License**: Proprietary / Educational Submission for CodeTitans India 2026
- **Repository**: [https://github.com/Pathik008/Inkloom-AI](https://github.com/Pathik008/Inkloom-AI)
