# Inkloom AI

**AI-Powered Brand Compliance & Marketing Content Review Platform**
*Built for CodeTitans India 2026 — Round 2*

---

## 1. Project Overview

**Inkloom AI** enables enterprises and marketing teams to manage versioned Brand Knowledge Bases (Brand Kits, Approved Facts, Compliance Rules, Disclaimers, Reference Documents), submit marketing content (text, social copy, PDFs, DOCX, images), run a **Hybrid Compliance Engine** (Deterministic Rule Engine + LangGraph RAG Semantic Engine), apply evidence-backed corrections, and govern sign-off through a **SHA-256 Cryptographically Bound Human Approval Workflow**.

**Core Engineering Rule:** Every compliance finding must be traceable to an applicable rule, approved brand fact, or supporting evidence chunk. When sufficient approved evidence is unavailable, findings are marked `UNVERIFIED` rather than fabricated.

---

## 2. Prerequisites

| Tool | Recommended Version | Verified on Workspace |
| :--- | :--- | :--- |
| **Node.js** | `>= 20.x` | `v24.20.0` (Installed) |
| **npm** | `>= 10.x` | `11.19.0` (Installed) |
| **Python** | `>= 3.11` | `3.13.7` (Installed) |
| **Git** | `>= 2.40` | `2.56.0.windows.4` (Installed) |
| **Docker & Docker Compose** | Docker Desktop (with Compose v2) | *Not currently installed on host* (Required to run containerised PostgreSQL 16 + `pgvector`; local SQLite fallback active in `development` mode) |

---

## 3. Environment Setup

Copy `.env.example` to `.env` in the project root before starting services:

```powershell
Copy-Item .env.example .env
```

Generate a secure random 64-character hex secret for `SECRET_KEY` and update `.env`:

```powershell
# Using Python
python -c "import secrets; print(secrets.token_hex(32))"

# Or using PowerShell
-join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Max 256) })

# Or using OpenSSL
openssl rand -hex 32
```

> **Security Guardrail:** The application enforces that `SECRET_KEY` must be configured, cannot be empty, must be at least 32 characters, and cannot match known template defaults. Application startup will fail safely if `SECRET_KEY` is missing or insecure.

Key environment variables in `.env`:
- `SECRET_KEY`: Cryptographically secure random signing key for `HS256` JWT tokens (minimum 32 characters; required).
- `JWT_ISSUER`: JWT issuer claim (`inkloom-ai-api`).
- `ACCESS_TOKEN_EXPIRE_MINUTES`: Token validity duration (`1440` minutes by default).
- `DATABASE_URL`: PostgreSQL + `psycopg` connection URI (`postgresql+psycopg://inkloom_user:...@localhost:5432/inkloom_db`).
- `ALLOW_SQLITE_DEV_FALLBACK`: Defaults to `false`. Set to `true` strictly for offline local unit tests without Docker.

Never commit `.env` files or real API keys to version control.

---

## 4. Database Setup & Alembic Migrations

> **Primary Production Database: PostgreSQL 16 + pgvector**
> - **Primary Database:** **PostgreSQL 16 + `pgvector`** (`pgvector/pgvector:pg16`) is the required primary database for Inkloom AI.
> - **Zero Silent Fallback:** If PostgreSQL is configured as the target database but port `5432` is closed, the application and Alembic migrations will fail fast with an explicit connection error (`PostgreSQL unreachable: port 5432 closed`). It will **never silently redirect** migrations or writes to SQLite.
> - **Opt-In Development Fallback:** When running offline local unit tests without Docker available, developers can explicitly opt into SQLite by setting `ALLOW_SQLITE_DEV_FALLBACK=true` or supplying a direct `sqlite:///` URL. When SQLite is active, foreign key constraints are strictly enforced via `PRAGMA foreign_keys=ON`.

### Starting PostgreSQL + `pgvector` (when Docker Desktop is available)
```powershell
docker compose -f infra/docker-compose.yml up -d
docker compose -f infra/docker-compose.yml ps
```

### Windows Prerequisites If Docker Is Not Yet Installed:
To run the live PostgreSQL 16 + pgvector instance on Windows:
1. Install [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/) (enabling WSL 2 backend).
2. Start Docker Desktop and run:
   ```powershell
   docker compose -f infra/docker-compose.yml up -d
   ```
3. Once the container is healthy on port `5432`, apply Alembic migrations:
   ```powershell
   cd backend
   .\.venv\Scripts\python.exe -m alembic upgrade head
   ```

### Alembic Migration Commands
Run all migration commands from the `backend/` directory using the virtual environment:

```powershell
cd backend

# Apply all migrations up to the latest revision (creates tables & seeds RBAC roles/permissions)
.\.venv\Scripts\python.exe -m alembic upgrade head

# Inspect current database revision
.\.venv\Scripts\python.exe -m alembic current

# View migration history
.\.venv\Scripts\python.exe -m alembic history --verbose

# Generate a new migration after modifying SQLAlchemy models
.\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe_change"

# Roll back one migration safely
.\.venv\Scripts\python.exe -m alembic downgrade -1
```

---

## 5. Backend Installation & Startup

```powershell
cd backend

# Install dependencies into virtual environment
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Apply database migrations
.\.venv\Scripts\python.exe -m alembic upgrade head

# Start FastAPI server on http://127.0.0.1:8000
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- **Root Health Endpoint**: `http://127.0.0.1:8000/health`
- **Versioned Health Endpoint**: `http://127.0.0.1:8000/api/v1/health`
- **Interactive Swagger UI**: `http://127.0.0.1:8000/docs`

---

## 6. Frontend Installation & Startup

```powershell
cd frontend

# Install packages
npm install

# Start Vite development server on http://127.0.0.1:5173
npm run dev -- --host 127.0.0.1 --port 5173

# Type-check & build production bundle
npm run lint
npm run build
```

- **Local Frontend URL**: `http://127.0.0.1:5173`

---

## 7. How to Register, Log In, and Manage Organisations

### Via the React UI (`http://127.0.0.1:5173`)
1. Open `http://127.0.0.1:5173` — unauthenticated users are automatically redirected to `/login`.
2. Click **Create an account & organisation workspace** (`/register`).
3. Enter your **Full Name**, **Work Email**, **Initial Organisation Name**, and **Password** (minimum 8 characters with at least one letter and one number).
4. Submitting creates your account, provisions your initial organisation, assigns you the `ADMIN` role, and signs you into the dashboard.
5. Navigate to **Org & RBAC Settings** (`/settings`) in the sidebar to:
   - Inspect your effective backend permissions (`users:read`, `users:manage`, `organisation:manage`, `brand:manage`, etc.).
   - Update organisation details.
   - Create additional isolated organisation workspaces and switch between them using the sidebar **Organisation Workspace** selector.
   - Add or provision team members with roles (`ADMIN`, `BRAND_MANAGER`, `CONTENT_CREATOR`, `REVIEWER`), update their roles, or remove members (with protection preventing removal/demotion of the last active `ADMIN`).
6. Click **Sign Out (Revoke Token)** in the sidebar footer to immediately revoke your JWT's `jti` on the backend and clear your session.

### Via REST API (PowerShell / `curl`)
```powershell
# 1. Register a user and initial organisation
$reg = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/auth/register" `
  -ContentType "application/json" `
  -Body '{"full_name":"Aarav Sharma","email":"aarav@inkloom.ai","password":"SecurePassword123","confirm_password":"SecurePassword123","organisation_name":"Inkloom Global"}'

$token = $reg.access_token

# 2. Fetch authenticated user profile & permissions (/api/v1/auth/me)
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/auth/me" `
  -Headers @{ Authorization = "Bearer $token" }

# 3. List accessible organisations
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/api/v1/organisations" `
  -Headers @{ Authorization = "Bearer $token" }

# 4. Revoke token (Logout)
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/auth/logout" `
  -Headers @{ Authorization = "Bearer $token" }
```

---

## 8. Running Automated Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -v -W error
```

---

## 9. Current Implementation Status

- **Implemented (Phase 1 — Foundation & Phase 2 — Authentication, Database & RBAC)**:
  - Complete project directory architecture (`frontend/`, `backend/`, `docs/`, `infra/`).
  - SQLAlchemy 2.1 models & Alembic migration `0001_phase2_auth_rbac` (`users`, `organisations`, `roles`, `permissions`, `role_permissions`, `organisation_memberships`, `revoked_tokens`).
  - Argon2id password hashing (`argon2-cffi`), signed `HS256` JWT tokens with `jti` revocation on logout, and sliding-window authentication rate limiting.
  - Multi-tenant organisation creation, member provisioning, role updates, member removal, last-active-`ADMIN` protection, and strict IDOR / cross-tenant isolation.
  - Predefined roles (`ADMIN`, `BRAND_MANAGER`, `CONTENT_CREATOR`, `REVIEWER`) mapped to 10 granular permissions enforced on the backend.
  - React + TypeScript Login, Registration, Protected Routes, Organisation Switcher, Role-Aware Sidebar, and Organisation & RBAC Settings UI.
  - 20 automated `pytest` tests covering all Phase 1 and Phase 2 functional and security requirements.
- **Planned (Phases 3–10)**:
  - Phase 3: Brand Hub, versioned Brand Kits, approved facts, and compliance rules.
  - Phase 4: Multimodal content upload (PDF, DOCX, Image OCR) and SHA-256 content revisions.
  - Phase 5: Deterministic compliance rule engine.
  - Phase 6: `pgvector` RAG retrieval and 11-node LangGraph semantic compliance engine.
  - Phase 7: Findings UI, evidence inspector, and integrated AI content editor.
  - Phase 8: SHA-256 bound human approval gate and append-only security audit logs.
  - Phase 9: Real database-backed analytics and exportable reports.
  - Phase 10: Security hardening, tenant-isolation test suite, and full deployment readiness.
