# Inkloom AI — CodeTitans Round 2 SaaS & Human Approval Guide

Welcome to the **Inkloom AI** Round 2 evaluation guide. This document provides complete instructions for judges to independently access, test, and evaluate the full end-to-end product workflow, including **Human Approvals**, **Multi-Tenant Customer Onboarding**, and **Persistent Compliance History**.

---

## 1. Quick Start & Access URLs

| Component | URL | Status / Notes |
| :--- | :--- | :--- |
| **Frontend Application** | `http://localhost:5173` | React 18, Vite, Tailwind CSS, Lucide icons |
| **Backend REST API** | `http://localhost:8000` | FastAPI 0.115, Python 3.12/3.13, Uvicorn |
| **Interactive API Docs** | `http://localhost:8000/docs` | Swagger / OpenAPI 3.0 documentation |
| **Health & DB Status** | `http://localhost:8000/health` | PostgreSQL 16 + pgvector connectivity |

---

## 2. Access Credentials & Independent Onboarding

Judges can evaluate Inkloom AI using **either** the pre-seeded demo account **or** by registering a completely new customer account and organisation workspace:

### Option A: Seeded Judge Demo Account
- **Email:** `judge@inkloom.ai`
- **Password:** `DemoJudge2026!`
- **Role:** `ADMIN` (Full tenant administrative privileges)
- **Organisation:** `Acme Financial Demo` (slug: `acme-financial-demo`)
- **Brand Kit:** `Acme Retail Banking Kit` (Version 1, `PUBLISHED`)

### Option B: Self-Service Customer Onboarding (Zero Dependencies)
New customers can independently register directly at:
- **Registration URL:** `http://localhost:5173/register`
- Fills: Full Name, Work Email, Organization Workspace Name, Password.
- Automatically provisions user account, new tenant organization, and `ADMIN` membership in one atomic transaction without manual database intervention.

---

## 3. Product Architecture & SaaS Features

Inkloom AI combines **deterministic compliance governance** with **real-world human collaboration workflows**:

1. **Deterministic Rule Engine (No Hallucinations):**
   - Violations are detected via strict pattern compilation, keyword triggers, and absence checks.
   - Every finding cites an exact character offset (`start`, `end`), matched violation substring, context excerpt, and explanation.

2. **ORM & Database Immutability (Phase 3.1 & 3.2):**
   - Published brand kits are immutable. Neither child rules nor container metadata can be modified or deleted once published (`BrandKitVersionStatus.PUBLISHED`).
   - Edits require branching a sequential `DRAFT` version (`Version 2`, `Version 3`), preserving a complete audit trail.

3. **Multi-Revision Submission Workflow & Diffing (Phase 4.1):**
   - Submissions track full revision lineages (`Revision 1`, `Revision 2`, ...).
   - Machine-applicable corrections replace prohibited terms and automatically append missing disclaimers and required terminology.
   - Displays a unified diff and score delta (`before` vs `after`) comparing revisions.

4. **Human Review, Approval Decisions & Discussion Trail (Phase 4.2):**
   - Formal approval lifecycle: `DRAFT` $\to$ `PENDING_REVIEW` $\to$ `APPROVED` | `CHANGES_REQUESTED` | `REJECTED`.
   - Submissions can be assigned to designated reviewers.
   - Reviewers record structured review notes and formal approval/rejection decisions.
   - Permanent audit log tracks reviewer identity, decision timestamps, and revision numbers in `brand_audit_logs`.

5. **Strict Multi-Tenant Isolation:**
   - All database records enforce `organisation_id` foreign keys and dependency injection.
   - Brand kits, compliance rules, submissions, and audit logs are strictly isolated between customer workspaces.

---

## 4. Step-by-Step Judge Evaluation Walkthrough

Follow these steps in your browser (`http://localhost:5173`):

### Step 1: Sign In
1. Navigate to `http://localhost:5173/login`.
2. Enter `judge@inkloom.ai` and `DemoJudge2026!`.
3. Click **Sign In** to land on the tenant dashboard.

### Step 2: Explore Brand Hub (`/brand-hub`)
1. Click **Brand Hub** in the sidebar navigation or visit `http://localhost:5173/brand-hub`.
2. Select **Acme Retail Banking Kit** from the brand kit dropdown.
3. Observe **Version 1** in `PUBLISHED` status:
   - Notice that the configuration form is locked with an immutability banner: *"This version is published and immutable."*
   - Review the 4 pre-configured rules:
     - `BAN-GR` (CRITICAL): Guaranteed Returns Prohibition ("guaranteed returns" → "potential returns")
     - `BAN-RF` (CRITICAL): Risk-Free Claims Prohibition ("risk-free" → "lower-risk")
     - `DISC-RISK` (HIGH): Market Risk Mandatory Disclaimer
     - `TERM-BRAND` (LOW): Official Brand Name Requirement ("Acme")

### Step 3: Run Deterministic Compliance Analysis (`/compliance-review`)
1. Click **Compliance Review** in the sidebar navigation.
2. Ensure **Target Brand Kit** is set to `Acme Retail Banking Kit`.
3. Click **"Load Judge Demo Sample"** to populate realistic financial marketing copy with deliberate violations.
4. Click **Run Compliance Check (New Submission)**.
5. Review the results:
   - **Status Badge:** `FAIL` (Score: 40/100).
   - **Highlighted Content Preview:** Prohibited terms highlighted directly in the text view.
   - **Detailed Finding Cards:** Exact matched violation `"guaranteed returns"`, context snippet, and missing market risk disclaimer.

### Step 4: Apply Machine Corrections & View Diff
1. In the score header, click the green button: **"Apply Suggested Corrections"**.
2. Observe the automatic transition:
   - A new immutable **Revision 2** is created and re-analyzed.
   - Prohibited terms are replaced with approved vocabulary.
   - The mandatory market risk disclaimer is appended.
   - Score improves, and a colorized unified diff displays all modifications.

### Step 5: Human Approval Lifecycle
1. Click **"Submit for Human Approval"** (`#btn-submit-for-approval`).
2. Enter a note for the reviewer: *"Corrections applied; disclaimer verified."*
3. Click **Confirm Submission**.
   - Observe the status badge updates to **`PENDING_REVIEW`**.
4. In the **Reviewer Action Center** (visible to `ADMIN` and `REVIEWER` roles):
   - Enter decision notes: *"Compliance verified. Approved for marketing deployment."*
   - Click **Approve Content** (`#btn-approve-content`).
   - Observe status badge transitions to **`APPROVED`** (emerald badge).
   - Observe the **Review History & Discussion** timeline logs the reviewer, timestamp, and notes.

### Step 6: Verify Persistence
1. Press `F5` to reload the page.
2. Verify that **Revision 2**, its `APPROVED` status, score comparison, and review history are fully preserved from PostgreSQL.

### Step 7: Independent Customer Onboarding (Zero Demo Dependencies)
1. Open an Incognito window or log out.
2. Navigate to `http://localhost:5173/register`.
3. Register a new customer: e.g., `Elena Vance` / `elena@nexis-retail.com` / `Nexis Retail Corp`.
4. Observe immediate provisioning and login to the new workspace.
5. Navigate to `/brand-hub`:
   - Verify **strict tenant isolation**: Acme's brand kits are not visible.
6. Create a new custom Brand Kit (`Nexis Core Kit`), configure custom rules, approve them, publish Version 1, and run compliance review!

---

## 5. Automated Verification Suites

Judges can execute all verification suites from the terminal:

### Full Playwright End-to-End Browser Journey (17 Steps in Real Chrome)
Executes the full journey in Google Chrome:
```powershell
& "backend\.venv-sqlalchemy-test\Scripts\python" backend/tests/test_browser_journey.py
```
*Result: 17/17 browser verification steps passing.*

### Backend Pytest Suite (66 Passed, 0 Failed)
```powershell
& "backend\.venv-sqlalchemy-test\Scripts\python" -m pytest backend/tests/test_stage4_2_approval_workflow.py backend/tests/test_stage4_compliance_workflow.py backend/tests/test_stage3_2_brand_kit_service_and_api.py backend/tests/test_stage3_1_brand_hub_db.py backend/tests/test_auth_and_rbac.py backend/tests/test_health.py -v
```

---

## 6. Public Deployment & Production Readiness

The application is configured for production SaaS deployment:

1. **Production Frontend Build:**
   - Tested and verified: `npm run build` compiles clean production bundle in `frontend/dist/` in 4.04s with zero TypeScript warnings.
2. **Environment Variable Configuration:**
   - Centralized in `backend/app/core/config.py` with pydantic validation.
   - Enforces minimum 32-character `SECRET_KEY`, non-default `POSTGRES_PASSWORD`, and restricts SQLite fallbacks in staging/production.
3. **Database Migrations:**
   - Alembic revisions 0001 through 0007 applied cleanly. Downgrade and re-upgrade safety verified.
4. **Tenant Isolation & Security:**
   - Cross-tenant data leaks prevented at database schema level and FastAPI dependency level.
   - RBAC matrix strictly enforced: `CONTENT_CREATOR` cannot approve their own submissions; `APPROVAL_DECIDE` required.
