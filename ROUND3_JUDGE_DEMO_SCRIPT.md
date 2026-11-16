# INKLOOM AI — ROUND 3 HACKATHON JUDGE DEMONSTRATION SCRIPT
**Event:** CodeTitans India 2026 — Round 3 (Finalist Stage)<br/>
**Team Name:** TITANIUM<br/>
**Project:** Inkloom AI (Enterprise Brand Compliance & Governance Engine)<br/>
**Target Duration:** 5 Minutes<br/>
**Live Application URL:** `http://127.0.0.1:5173` (Local Dev) / Production Ingress<br/>

---

## Demonstration Preparation & Setup

Before starting the live demonstration, ensure:
1. Vite Frontend is running on `http://127.0.0.1:5173`.
2. FastAPI Backend is healthy on `http://127.0.0.1:8000/health`.
3. PostgreSQL 16 + pgvector container is healthy on port `5432`.
4. Open two browser windows / profiles:
   - **Window 1 (Author/Judge):** Pre-loaded at `http://127.0.0.1:5173/login`
   - **Window 2 (Independent Reviewer):** Incognito / separate session at `http://127.0.0.1:5173/login`

---

## 5-Minute Demonstration Flow

```
[00:00 - 00:45] Minute 1: Problem, Solution & High-Level Architecture
[00:45 - 01:30] Minute 2: Brand Hub, Immutability & Guideline Ingestion
[01:30 - 02:45] Minute 3: Compliance Analysis, Span Pinpointing & 1-Click Remediation
[02:45 - 04:00] Minute 4: Dual-Control Maker-Checker & Reviewer Decision
[04:00 - 05:00] Minute 5: Immutable Audit Ledger, Technical Differentiators & Wrap-up
```

---

### MINUTE 1: Problem Statement & Inkloom AI Overview (00:00 – 00:45)

**Screen to Show:** `http://127.0.0.1:5173/login` $\rightarrow$ Submit login $\rightarrow$ `http://127.0.0.1:5173/` (Dashboard)

> **Speaker Script:**
> *"Distinguished judges, in heavily regulated industries like retail banking and financial services, marketing and compliance operate in constant friction. A single unsubstantiated guarantee or missing risk disclaimer can trigger statutory penalties from regulators like SEBI and FTC, alongside catastrophic brand erosion.*
>
> *Today, marketing teams either wait weeks for manual compliance review or risk publishing non-compliant copy. Traditional LLM checkers hallucinate or give vague feedback without citing the exact regulatory clause.*
>
> *Meet **Inkloom AI** — an enterprise-grade multi-agent compliance engine that guarantees mathematical, deterministic precision. Every claim is verified against version-locked Brand Guidelines, pinpointed to exact character offsets, and remediated in one click under strict Maker-Checker dual control."*

**Visual Action:**
- Log in using `judge@inkloom.ai` / `<DEMO_PASSWORD_PROVIDED_SEPARATELY>` (or click "Use Demo Judge Access").
- Highlight the **Live Telemetry Cards** on the Dashboard: Total Submissions, Approval Rates, and Pending Queues computed directly from SQL aggregations.

---

### MINUTE 2: Brand Hub, Immutability & Guideline Ingestion (00:45 – 01:30)

**Screen to Show:** Navigate to `http://127.0.0.1:5173/brand-hub`

> **Speaker Script:**
> *"At the core of Inkloom AI is the **Brand Hub**. Compliance rules cannot be arbitrary prompts — they are cryptographically locked within versioned Brand Kits.*
>
> *Here in our **Acme Financial Demo** workspace, we see the published **Acme Retail Banking Kit v1.0.0**. Notice this version is PUBLISHED: by database trigger enforcement, it is 100% immutable. No user can tamper with active rules or inject unapproved terms.*
>
> *Our compliance rules define four strict regulatory standards:*
> 1. `BAN-GR` (Critical): *Prohibition of guaranteed return promises.*
> 2. `BAN-RF` (Critical): *Prohibition of risk-free claims.*
> 3. `DISC-RISK` (High): *Mandatory statutory market risk disclaimer.*
> 4. `TERM-BRAND` (Low): *Mandatory corporate wordmark requirement.*
>
> *To update rules, we created Draft Version 2, which ingests multimodal guideline documents — extracting text from PDFs, policy Word docs, and even graphic standards using OCR with sentence-aware chunking."*

**Visual Action:**
- Point out the 4 approved rules with their severity badges (Critical, High, Low).
- Toggle Draft Version v2 to show the ingested `.pdf` and `.txt` guideline documents.

---

### MINUTE 3: Compliance Analysis, Span Pinpointing & 1-Click Remediation (01:30 – 02:45)

**Screen to Show:** Navigate to `http://127.0.0.1:5173/compliance-review`

> **Speaker Script:**
> *"Now let's examine the heart of our platform: the **Compliance Review Workbench**.*
>
> *Here is an evaluation marketing copy submitted for our retail banking campaign. Look at the deterministic score: **0 / 100 — FAIL**.*
>
> *Unlike generic chatbot wrappers, Inkloom AI does not provide vague conversational feedback. Notice how our deterministic engine pinpoints the exact character coordinates:*
> - *Span `1511–1529`: Flags `"guaranteed returns"` with surrounding context.*
> - *Spans `1688–1697` and `3080–3089`: Flags `"risk-free"` claims.*
> - *Document Level: Flags the missing mandatory SEBI market risk disclosure.*
>
> *Now watch what happens when the author clicks **Apply 1-Click Suggestions**:*
> *The system generates **Revision 2** as an immutable child record with a SHA-256 hash. Prohibited claims are replaced with compliant alternatives like 'potential returns' and 'lower-risk', and the mandatory disclaimer is appended.*
>
> *The engine automatically re-analyzes Revision 2 in real time:*
> *Score jumps from **0 to 100 — PASS**!*
> *And notice: the original Revision 1 is never overwritten; both revisions remain linked in complete lineage with a 24-line unified diff."*

**Visual Action:**
- Show highlighted spans in the text viewer.
- Click Revision 2 toggle to demonstrate the 100/100 score jump and 0 remaining violations.

---

### MINUTE 4: Dual-Control Maker-Checker & Independent Review (02:45 – 04:00)

**Screen to Show:** Window 1 (Submitter view) $\rightarrow$ Switch to Window 2 (`http://127.0.0.1:5173/approvals` as Independent Reviewer)

> **Speaker Script:**
> *"In enterprise banking, content creators cannot approve their own marketing copy. Inkloom AI enforces the regulatory **Maker-Checker principle**.*
>
> *If the author (`judge@inkloom.ai`) attempts to approve Revision 1 or Revision 2, our backend service layer immediately halts the request with **HTTP 403 Forbidden: Submitter cannot approve their own submission**.*
>
> *Now let's switch to our second window where **Independent Compliance Officer** (`independent_reviewer@inkloom.ai`) is logged in.*
>
> *In the **Approval Inbox**:*
> - *For Revision 1 (Score 0): The independent reviewer inspected the violations and executed a **REJECT** decision with formal regulatory feedback. Once rejected, status is locked — any subsequent attempt to mutate it returns **HTTP 409 Conflict**.*
> - *For Revision 2 (Score 100): The reviewer reviewed the unified diff, verified that all violations were resolved, and executed an **APPROVE** decision.*
>
> *Both evaluation states are cleanly preserved for your inspection."*

**Visual Action:**
- Show the Approval Inbox table with Revision 1 (`REJECTED`) and Revision 2 (`APPROVED`).
- Click **Inspect** to display the detailed modal showing the reviewer's persisted commentary and decision timestamps.

---

### MINUTE 5: Immutable Audit Ledger, Differentiators & Wrap-up (04:00 – 05:00)

**Screen to Show:** Inside the Review Modal $\rightarrow$ Review Action Log & Database Audit Trail

> **Speaker Script:**
> *"Every single action taken across this platform — document upload, version creation, revision submission, reviewer commentary, and final approval — is recorded in our append-only `brand_audit_logs` table.*
>
> *To guarantee statutory non-repudiation, we deployed a custom PostgreSQL trigger (`fn_validate_and_protect_brand_audit_logs`). If anyone attempts a direct SQL `UPDATE` or `DELETE` on the audit logs, the database aborts with error `[P0005]: brand_audit_logs are append-only`.*
>
> *To summarize our core differentiators:*
> 1. **Zero Hallucination Guarantee:** *Deterministic regex and AST parsing guarantees 100% reproducible compliance scoring.*
> 2. **Multi-Tenant Isolation:** *Database-level tenant scoping prevents cross-organisation data leakage.*
> 3. **Defense-in-Depth Governance:** *Maker-Checker controls and trigger-level immutability.*
> 4. **Multimodal Guideline Ingestion:** *PDF and OCR ingestion with pgvector 1024-dimension semantic retrieval.*
>
> *Thank you. Team TITANIUM is ready for your questions."*

---

## Evaluation Reference Table for Judges

| Evaluation Dimension | Where to Verify in Live UI | Verification Endpoint / Artifact |
| :--- | :--- | :--- |
| **Authentication & RBAC** | Top Right Header (User Profile & Org Switcher) | `POST /api/v1/auth/login` |
| **Dashboard Metrics** | `/` (Home View) | `GET /api/v1/organisations/{id}/compliance/metrics` |
| **Brand Rules & Immutability** | `/brand-hub` | `GET .../versions/{id}/rules` |
| **Document Ingestion & OCR** | `/brand-hub` (Draft v2 documents) | `GET .../versions/{id}/documents` |
| **Compliance Scoring (0 vs 100)** | `/compliance-review` | `GET .../submissions/{id}` |
| **1-Click AI Remediation & Diff** | `/compliance-review` | `POST .../submissions/{id}/apply-corrections` |
| **Maker-Checker Block (403)** | Action footer on `/compliance-review` | `POST .../submissions/{id}/decide` |
| **Approval / Rejection Inbox** | `/approvals` | `GET .../compliance/submissions` |
| **Append-Only Audit Log** | Modal on `/approvals` $\rightarrow$ Action Log | PostgreSQL table `brand_audit_logs` |
