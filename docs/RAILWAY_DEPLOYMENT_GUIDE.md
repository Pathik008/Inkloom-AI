# Inkloom AI — Railway Cloud Deployment Guide

This guide describes the complete procedure for deploying Inkloom AI to [Railway](https://railway.com) using its managed infrastructure.

---

## 1. Cloud Service Architecture

The Inkloom AI production deployment on Railway consists of three decoupled services:

```mermaid
flowchart LR
    User[Web Client] -->|HTTPS :443| Frontend[inkloom-frontend\nNginx + React SPA]
    Frontend -->|Internal / Private Mesh\n${BACKEND_URL}/api| Backend[inkloom-backend\nFastAPI + Uvicorn]
    Backend -->|PostgreSQL Protocol\n${DATABASE_URL}| Database[(PostgreSQL 16\n+ pgvector 0.8+)]
    Backend -->|Persistent Volume| Uploads[Volume: /app/storage/uploads]
    Database -->|Persistent Volume| PgData[Volume: /var/lib/postgresql/data]
```

1. **Database Service (`inkloom-database`)**:
   - Template: **PostgreSQL with pgvector** (or standard Railway PostgreSQL upgraded with `pgvector`).
   - Image: `pgvector/pgvector:pg16`.
   - Persistence: Railway Persistent Volume attached at `/var/lib/postgresql/data`.
2. **Backend API Service (`inkloom-backend`)**:
   - Runtime: Python 3.12 (via [backend/Dockerfile](file:///c:/Users/Win-11/Desktop/My%20World/backend/Dockerfile)).
   - Root directory in repo: `backend` (or repo root pointing to `backend/Dockerfile`).
   - Lifecycle:
     1. Probes DB connectivity with bounded retries (up to 30s).
     2. Runs Alembic migrations (`alembic upgrade head`).
     3. Conditionally runs idempotent demo seeder if `SEED_DEMO_DATA=true`.
     4. Launches Uvicorn on `${PORT:-8000}`.
   - Persistence: Railway Persistent Volume mounted at `/app/storage/uploads`.
3. **Frontend Ingress Service (`inkloom-frontend`)**:
   - Runtime: Nginx Alpine Slim serving Vite production assets (via [frontend/Dockerfile](file:///c:/Users/Win-11/Desktop/My%20World/frontend/Dockerfile)).
   - Root directory in repo: `frontend` (or repo root pointing to `frontend/Dockerfile`).
   - Routing:
     - `/` $\rightarrow$ React SPA (`index.html`).
     - `/healthz` $\rightarrow$ Standalone frontend health probe (`200 OK`).
     - `/health` $\rightarrow$ Reverse-proxied system health check (`${BACKEND_URL}/health`).
     - `/api/*` $\rightarrow$ Reverse-proxied backend API (`${BACKEND_URL}/api/*`).

---

## 2. Environment Variables Specification

### A. Database Service (`inkloom-database`)
Railway automatically provisions these variables:
- `POSTGRES_USER`: (e.g. `postgres`)
- `POSTGRES_PASSWORD`: *(Auto-generated)*
- `POSTGRES_DB`: (e.g. `railway`)
- `POSTGRES_PORT`: `5432`
- `DATABASE_URL`: `postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${RAILWAY_PRIVATE_DOMAIN}:5432/${POSTGRES_DB}`

---

### B. Backend API Service (`inkloom-backend`)

| Variable Name | Classification | Default / Source | Description |
|---|---|---|---|
| `APP_ENV` | Configuration | `production` | Production environment flag. |
| `DATABASE_URL` | Railway Reference | `${{inkloom-database.DATABASE_URL}}` | Auto-normalized to `postgresql+psycopg://`. |
| `SECRET_KEY` | Secret | *Generate with OpenSSL* | Secret key for cryptographic signing. |
| `JWT_SECRET_KEY` | Secret | *Generate with OpenSSL* | Secret key for JWT access and refresh tokens. |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Configuration | `60` | JWT access token lifetime. |
| `ALLOW_SQLITE_DEV_FALLBACK` | Safeguard | `false` | Strictly disables SQLite fallback. |
| `UPLOAD_STORAGE_DIR` | Configuration | `/app/storage/uploads` | Path to persistent uploads volume. |
| `CORS_ORIGINS` | Ingress Security | `["https://${{inkloom-frontend.RAILWAY_PUBLIC_DOMAIN}}"]` | Allowed frontend browser origin(s). |
| `TRUSTED_PROXIES` | Ingress Security | `*` | Ingress proxy CIDRs / wildcards. |
| `SEED_DEMO_DATA` | Optional Demo | `false` (or `true` for demo) | Enables judge/demo data seeding. |
| `ALLOW_DEMO_SEED` | Safeguard | `false` (or `true` if seeding) | Mandatory safety gate for demo seeding. |
| `DEMO_ADMIN_PASSWORD` | Secret | *Set unique password* | Mandatory non-default password if seeding. |
| `LLM_API_KEY` | Optional External | `""` | Optional Gemini/OpenAI API key. |
| `LLM_PROVIDER` | Optional External | `openai_compatible` | Provider type if live LLM is configured. |

> [!NOTE]
> Generate secrets locally before adding them to Railway:
> ```powershell
> # PowerShell / Bash:
> openssl rand -hex 32
> ```

---

### C. Frontend Service (`inkloom-frontend`)

| Variable Name | Type | Value / Reference | Purpose |
|---|---|---|---|
| `PORT` | System | Provided by Railway (e.g. `80` or dynamic) | Listening port for Nginx. |
| `BACKEND_URL` | Runtime Reference | `http://${{inkloom-backend.RAILWAY_PRIVATE_DOMAIN}}:${{inkloom-backend.PORT}}` | Private network mesh proxy target. |
| `VITE_API_BASE_URL` | Build Argument | `""` *(empty string)* | Empty string forces frontend to use relative `/api` paths through Nginx reverse proxy. |

---

## 3. Step-by-Step Railway Deployment Sequence

### Step 1: Create a Railway Project
1. Log in to [Railway Dashboard](https://railway.com).
2. Click **New Project** $\rightarrow$ **Empty Project**.
3. Name the project `inkloom-ai-production`.

### Step 2: Deploy the PostgreSQL + pgvector Database
1. In the project canvas, click **Create** $\rightarrow$ **Database** $\rightarrow$ **Add PostgreSQL**.
2. If using Railway's default PostgreSQL template, verify that `pgvector` extension is available.
   *(Alternatively, deploy from Docker Hub image `pgvector/pgvector:pg16` with a Persistent Volume mounted at `/var/lib/postgresql/data`).*
3. Rename the service to `inkloom-database`.
4. In the service **Settings**, verify or add a Persistent Volume at `/var/lib/postgresql/data`.

### Step 3: Deploy the Backend API Service
1. In the project canvas, click **Create** $\rightarrow$ **GitHub Repo** (select this repository).
2. Rename the service to `inkloom-backend`.
3. In **Settings**:
   - **Root Directory**: `backend` (or repo root with `backend/railway.json`).
   - **Dockerfile Path**: `backend/Dockerfile`.
   - **Networking**: Click **Generate Private Domain** (e.g. `inkloom-backend.railway.internal`).
   - **Public Networking**: Optional (only generate a public domain if external direct API access is required; otherwise leave private).
4. In **Volumes**:
   - Click **Add Volume** $\rightarrow$ Set Mount Path to `/app/storage/uploads`.
5. In **Variables**:
   - Add all variables listed in Section 2B.
   - Reference `DATABASE_URL` using `${{inkloom-database.DATABASE_URL}}`.
   - Configure `SECRET_KEY` and `JWT_SECRET_KEY` with strong random 64-character hex strings.
6. Under **Deploy**:
   - Set **Healthcheck Path** to `/health`.
   - Set **Healthcheck Timeout** to `30`.

### Step 4: Deploy the Frontend Service
1. Click **Create** $\rightarrow$ **GitHub Repo** (select this repository).
2. Rename the service to `inkloom-frontend`.
3. In **Settings**:
   - **Root Directory**: `frontend`.
   - **Dockerfile Path**: `frontend/Dockerfile`.
   - **Networking**: Click **Generate Public Domain** (e.g. `inkloom-ai.up.railway.app`).
4. In **Variables**:
   - Set `BACKEND_URL`: `http://${{inkloom-backend.RAILWAY_PRIVATE_DOMAIN}}:${{inkloom-backend.PORT}}`.
5. Under **Deploy**:
   - Set **Healthcheck Path** to `/healthz`.
   - Set **Healthcheck Timeout** to `20`.

### Step 5: Finalize CORS Configuration
1. Copy the generated public frontend domain (e.g. `https://inkloom-ai.up.railway.app`).
2. Go back to `inkloom-backend` $\rightarrow$ **Variables**.
3. Update `CORS_ORIGINS`:
   ```json
   ["https://inkloom-ai.up.railway.app"]
   ```
4. Railway will automatically redeploy `inkloom-backend` with the locked-down CORS origin.

---

## 4. Health-Check Configuration Summary

| Service | Health Check Endpoint | Target Port | Expected HTTP Status |
|---|---|---|---|
| `inkloom-database` | `pg_isready -U $POSTGRES_USER` | `5432` | `0` (Success) |
| `inkloom-backend` | `GET /health` | Dynamic `${PORT}` | `HTTP 200 OK` (checks DB + engine) |
| `inkloom-frontend` | `GET /healthz` | Dynamic `${PORT}` | `HTTP 200 OK` (independent web check) |

---

## 5. Migration & Boot Strategy

The startup sequence in [backend/entrypoint.sh](file:///c:/Users/Win-11/Desktop/My%20World/backend/entrypoint.sh) executes deterministically:
1. **Bounded DB Readiness Loop**:
   Runs Python probe up to 15 retries (2s interval, total 30s) testing `SELECT 1`.
2. **Alembic Migration Execution**:
   Executes `alembic upgrade head`. Applies all pending migrations up to `0007_content_approvals`.
3. **Idempotent Seeding Guard**:
   If `SEED_DEMO_DATA=true`, runs `app.scripts.seed_demo`. Fails fast on non-zero exit to alert Railway.
4. **Server Execution**:
   Executes `exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers`.

---

## 6. Post-Deployment Smoke Tests

Once all three services report **Active** and **Healthy** on Railway:

### 1. Ingress & SPA Delivery
```bash
curl -I https://<your-frontend-domain>.up.railway.app/
```
*Expected*: `HTTP/1.1 200 OK`, `Content-Type: text/html`.

### 2. Standalone Frontend Health Check
```bash
curl -i https://<your-frontend-domain>.up.railway.app/healthz
```
*Expected*: `HTTP/1.1 200 OK`, Body: `OK`.

### 3. Proxied System & Database Health Check
```bash
curl -i https://<your-frontend-domain>.up.railway.app/health
```
*Expected*: `HTTP/1.1 200 OK`, JSON:
```json
{
  "status": "healthy",
  "service": "Inkloom AI",
  "database_connected": true,
  "database_status": "connected (PostgreSQL 16 + pgvector)"
}
```

### 4. Authenticated API Check
```bash
curl -X POST https://<your-frontend-domain>.up.railway.app/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"judge@inkloom.ai","password":"<your_configured_demo_password>"}'
```
*Expected*: `HTTP/1.1 200 OK` with valid JWT `access_token` and active organisation.

---

## 7. Rollback Procedure

In the event of a deployment defect:

1. **Service Rollback (Zero Downtime)**:
   - In the Railway Dashboard, select the affected service (`inkloom-backend` or `inkloom-frontend`).
   - Click the **Deployments** tab.
   - Locate the previous healthy deployment.
   - Click the three dots ($\cdots$) $\rightarrow$ **Rollback to this deployment**.
2. **Database Schema Downgrade (If Needed)**:
   - If a bad migration was applied:
     ```bash
     railway run alembic downgrade -1
     ```
3. **Storage Preservation**:
   - Rolling back code deployments **never** touches persistent volumes mounted at `/var/lib/postgresql/data` or `/app/storage/uploads`.
