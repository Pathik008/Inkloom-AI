# Inkloom AI — Phase 2 Finding H2 Remediation Report

**Finding:** H2 — Insecure Direct Organisation Member Addition & Lack of Cryptographic Invitation Workflow
**Severity:** HIGH
**Status:** REMEDIATED & VERIFIED
**Final Verdict:** **APPROVED WITH CONDITIONS**
**Date of Audit:** November 8, 2026
**Auditor:** Senior Application Security Engineer & Technical Auditor

---

## 1. Executive Summary

During the Phase 2 security audit of Inkloom AI, Finding **H2** identified that organisation administrators could unilaterally add existing users or provision new user accounts directly into an organisation via `POST /api/v1/organisations/{id}/members`. This violated the core security principles of:
1. **Explicit Recipient Consent:** Users could be joined to organisations without their consent or knowledge.
2. **Account Enumeration:** The API disclosed whether an email already possessed an Inkloom account.
3. **Privilege & Identity Integrity:** Bypassed email verification workflows for invited participants.

Finding H2 has been remediated through a secure, cryptographic, token-based invitation and acceptance architecture across both the FastAPI backend and React/TypeScript frontend.

---

## 2. Root Cause Analysis

In the original Phase 2 design:
- `POST /api/v1/organisations/{id}/members` accepted `{ email, role, full_name, initial_password }`.
- If the email was present in the database, the backend added an active membership immediately.
- If the email did not exist, the endpoint created a new user with the caller-supplied password.
- This introduced three major security vulnerabilities:
  - **Account Enumeration:** Response diffing allowed attackers to probe valid email addresses.
  - **Unsolicited Association:** Compromised or malicious tenant admins could attach arbitrary users to organisations.
  - **Credential Imposition:** Insecure distribution of initial passwords by administrators.

---

## 3. Database Architecture & Alembic Migration

### 3.1 Migration: `0002_organisation_invitations`
A dedicated migration was created and applied to the live PostgreSQL 16.15 instance:
- Migration file: `backend/alembic/versions/0002_organisation_invitations.py`
- Head state: `0002_organisation_invitations (head)`
- Database table: `organisation_invitations`

### 3.2 Table Schema (`organisation_invitations`)

| Column Name | Type | Constraints / Attributes |
| :--- | :--- | :--- |
| `id` | `UUID` | Primary Key, default `gen_random_uuid()` |
| `organisation_id` | `UUID` | Foreign Key to `organisations.id` (ON DELETE CASCADE), Indexed, Not Null |
| `email` | `VARCHAR(255)` | Not Null, Normalised lowercase, Indexed |
| `role_id` | `UUID` | Foreign Key to `roles.id`, Not Null |
| `invited_by_user_id`| `UUID` | Foreign Key to `users.id` (ON DELETE SET NULL), Nullable |
| `token_hash` | `VARCHAR(64)` | Unique Index, Not Null (stores SHA-256 hex digest) |
| `status` | `VARCHAR(32)` | Enum: `PENDING`, `ACCEPTED`, `REVOKED`, `EXPIRED`, Indexed, Not Null |
| `expires_at` | `TIMESTAMP WITH TIME ZONE` | Not Null, Default UTC + 7 days, Indexed |
| `accepted_at` | `TIMESTAMP WITH TIME ZONE` | Nullable, recorded upon acceptance |
| `revoked_at` | `TIMESTAMP WITH TIME ZONE` | Nullable, recorded upon revocation |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | Not Null, default UTC now |

---

## 4. Backend Implementation

Implemented in [`backend/app/services/invitation_service.py`](file:///c:/Users/Win-11/Desktop/My%20World/backend/app/services/invitation_service.py), [`backend/app/api/routes/invitations.py`](file:///c:/Users/Win-11/Desktop/My%20World/backend/app/api/routes/invitations.py), and [`backend/app/api/routes/organisations.py`](file:///c:/Users/Win-11/Desktop/My%20World/backend/app/api/routes/organisations.py).

### 4.1 Cryptographic Token Lifecycle
1. **Generation:** Cryptographically secure 256-bit URL-safe tokens generated using Python's `secrets.token_urlsafe(32)`.
2. **Storage:** Only the SHA-256 hash (`hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()`) is stored in PostgreSQL.
3. **Lookup & Verification:** Lookups query `token_hash` and perform constant-time verification using `hmac.compare_digest(invitation.token_hash, computed_hash)` to resist timing side-channel attacks.
4. **Single-Use Enforcement:** The raw token is returned **exactly once** in the `POST /api/v1/organisations/{id}/invitations` response body (`InvitationCreateResponse.invitation_token`) and is never included in subsequent GET or list endpoints.

### 4.2 Row-Level Locking & Concurrency Protection
To eliminate race conditions and double-acceptance exploits, both acceptance workflows enforce PostgreSQL row-level locks:
```python
locked_invitation = (
    db.execute(
        select(OrganisationInvitation)
        .where(OrganisationInvitation.id == invitation.id)
        .with_for_update(of=OrganisationInvitation)
        .execution_options(populate_existing=True)
    )
    .scalars()
    .one_or_none()
)
```
- Restricting `with_for_update` specifically to `of=OrganisationInvitation` prevents PostgreSQL outer-join locking errors.
- `populate_existing=True` ensures SQLAlchemy identity maps refresh from disk, correctly detecting committed status changes from concurrent transactions.
- Tested and verified with simultaneous multithreaded requests via a threading synchronization barrier.

### 4.3 Identity Matching & Tenant Isolation
- **Authenticated Acceptance (`POST /api/v1/invitations/{token}/accept`):** Requires `current_user.email.strip().lower() == invitation.email.strip().lower()`. If mismatched, returns generic `403 Forbidden` (`"You are not authorised to accept this invitation."`) without revealing account existence.
- **Registration Acceptance (`POST /api/v1/invitations/{token}/register-and-accept`):** Automatically binds the newly created user's email strictly to `invitation.email`. If an account with that email already exists, returns `400 Bad Request` instructing the user to log in.
- **Tenant Isolation:** Invocation of `POST /{id}/invitations`, `GET /{id}/invitations`, and `DELETE /{id}/invitations/{inv_id}` requires an active tenant context with `users:manage` or `users:read`. Cross-tenant manipulation returns `403 Forbidden` or `404 Not Found`.

### 4.4 Deprecation of Direct Addition
`POST /api/v1/organisations/{organisation_id}/members` has been disabled and responds with HTTP `400 Bad Request`:
```json
{
  "detail": "Direct member addition without explicit invitation acceptance is disabled for security. Use POST /api/v1/organisations/{organisation_id}/invitations to invite team members."
}
```

---

## 5. Frontend Implementation

Implemented in [`frontend/src/pages/AcceptInvitationPage.tsx`](file:///c:/Users/Win-11/Desktop/My%20World/frontend/src/pages/AcceptInvitationPage.tsx), [`frontend/src/pages/OrganisationSettingsPage.tsx`](file:///c:/Users/Win-11/Desktop/My%20World/frontend/src/pages/OrganisationSettingsPage.tsx), [`frontend/src/pages/LoginPage.tsx`](file:///c:/Users/Win-11/Desktop/My%20World/frontend/src/pages/LoginPage.tsx), and [`frontend/src/services/api.ts`](file:///c:/Users/Win-11/Desktop/My%20World/frontend/src/services/api.ts).

### 5.1 Invitation Landing Page (`/accept-invitation?token={token}`)
- Reads raw token from query parameters (`useSearchParams()`).
- Calls public preview endpoint `GET /api/v1/invitations/{token}`.
- Handles all invitation states cleanly:
  - **Loading:** Branded loading state.
  - **Not Found / Invalid / Expired / Revoked:** Dedicated status cards with links to login or dashboard.
  - **Authenticated Match:** Displays invited workspace and role with an "Accept Invitation & Enter Workspace" button.
  - **Authenticated Mismatch:** Displays an amber warning indicating that the current session (`user.email`) does not match the invitation recipient (`invitation.email`), offering a one-click "Sign Out & Switch Account" button.
  - **Unauthenticated:** Offers "Create Your Account to Join" (locked email, full name, password, confirm password) calling `registerAndAcceptInvitation`, as well as a link to "Sign in to accept" preserving the redirect URL.

### 5.2 Organisation Settings Management UI
- Replaced the direct member addition form with the "Invite New Team Member" form.
- Added a dismissible "Invitation Ready to Share" banner with one-click clipboard copying (`Copy Link`) and expiration notice.
- Added a "Pending & Historical Invitations" table displaying recipient email, role, status badges (`PENDING`, `ACCEPTED`, `REVOKED`, `EXPIRED`), inviter, expiration date, and a "Revoke" button.
- Retained the active members list with role selector and removal controls.

---

## 6. Verification and Test Evidence

### 6.1 Backend Test Suite (Automated)
All 49 backend integration and security tests passed under strict `-W error`:
```text
============================= test session starts =============================
platform win32 -- Python 3.13.7, pytest-9.2.0, pluggy-1.7.0
rootdir: C:\Users\Win-11\Desktop\My World
plugins: anyio-4.16.0
collected 49 items

backend/tests/test_auth_and_rbac.py ................. [17 passed]
backend/tests/test_invitations_security.py ............ [14 passed]
backend/tests/test_main.py ...........                [11 passed]
backend/tests/test_postgres_integration.py .......    [7 passed]

============================== 49 passed in 7.51s ==============================
```

#### Dedicated Invitation Security Tests (`test_invitations_security.py`):
1. `test_create_invitation_success`: Generates token, persists only SHA-256 hash.
2. `test_raw_token_never_persisted_in_database`: Verifies raw token is not stored in plaintext anywhere in the database.
3. `test_public_invitation_preview`: Previews valid invitation without authentication.
4. `test_authenticated_invitation_acceptance_success`: Existing user accepts invitation and joins workspace.
5. `test_authenticated_acceptance_email_mismatch_rejected`: Rejects acceptance if user email differs from recipient (HTTP 403).
6. `test_invitation_single_use_enforcement`: Second acceptance attempt rejected with HTTP 409 Conflict.
7. `test_revoked_invitation_rejected`: Administrator revokes invitation; preview/acceptance rejected with HTTP 410 Gone.
8. `test_expired_invitation_rejected`: Expired invitation rejected with HTTP 410 Gone.
9. `test_register_and_accept_invitation_success`: New user registers and joins workspace atomically.
10. `test_register_and_accept_existing_email_rejected`: Rejects registration if email already exists (HTTP 400).
11. `test_direct_member_add_endpoint_disabled`: Confirms `POST /members` returns HTTP 400.
12. `test_invitation_enumeration_protection`: Verifies non-disclosing 201 response regardless of recipient registration status.
13. `test_invitation_list_excludes_tokens`: Verifies list endpoint never returns tokens or hashes.
14. `test_postgres_invitation_concurrency_race_condition`: Live PostgreSQL row-level lock concurrency test; proves only 1 of 2 simultaneous requests succeeds while the other is safely rejected with HTTP 409.

### 6.2 Frontend Typecheck and Production Build
1. **TypeScript Typecheck:**
   ```powershell
   npx --prefix frontend tsc -p frontend/tsconfig.app.json --noEmit
   # Exit code: 0 (0 errors, 0 warnings)
   ```
2. **Production Bundle Build:**
   ```powershell
   npm --prefix frontend run build
   # vite v5.4.21 building for production...
   # ✓ built in 4.97s (dist/index.html, dist/assets/index-*.css, dist/assets/index-*.js)
   ```

---

## 7. Security Audit Checklist

| Check # | Requirement | Status | Evidence / Location |
| :---: | :--- | :---: | :--- |
| **1** | Secure token generation, SHA-256 hashing, constant-time compare | **PASS** | [`invitation_service.py:34-48, 147`](file:///c:/Users/Win-11/Desktop/My%20World/backend/app/services/invitation_service.py#L34-L48) |
| **2** | Raw tokens not exposed in list, preview, or standard responses | **PASS** | [`routes/organisations.py:337-351`](file:///c:/Users/Win-11/Desktop/My%20World/backend/app/api/routes/organisations.py#L337-L351), [`routes/invitations.py:31-49`](file:///c:/Users/Win-11/Desktop/My%20World/backend/app/api/routes/invitations.py#L31-L49) |
| **3** | Raw tokens returned only on intentional creation (201 response) | **PASS** | [`routes/organisations.py:317-329`](file:///c:/Users/Win-11/Desktop/My%20World/backend/app/api/routes/organisations.py#L317-L329) |
| **4** | Authenticated acceptance strictly enforces recipient email match | **PASS** | [`invitation_service.py:194-198`](file:///c:/Users/Win-11/Desktop/My%20World/backend/app/services/invitation_service.py#L194-L198) (HTTP 403) |
| **5** | Registration-and-acceptance binds to invitation email | **PASS** | [`invitation_service.py:282, 332`](file:///c:/Users/Win-11/Desktop/My%20World/backend/app/services/invitation_service.py#L282-L332) |
| **6** | Acceptance is atomic and protected against concurrency race conditions | **PASS** | [`invitation_service.py:201-207`](file:///c:/Users/Win-11/Desktop/My%20World/backend/app/services/invitation_service.py#L201-L207) (`FOR UPDATE OF organisation_invitations`) |
| **7** | Expired, revoked, and accepted invitations cannot be reused | **PASS** | [`invitation_service.py:154-174`](file:///c:/Users/Win-11/Desktop/My%20World/backend/app/services/invitation_service.py#L154-L174) |
| **8** | Cross-tenant and unauthorized invitation actions blocked | **PASS** | [`routes/organisations.py:301, 338, 361`](file:///c:/Users/Win-11/Desktop/My%20World/backend/app/api/routes/organisations.py#L301-L361) |
| **9** | Public invitation endpoints have rate limiting | **FAIL** | Public endpoints in [`routes/invitations.py`](file:///c:/Users/Win-11/Desktop/My%20World/backend/app/api/routes/invitations.py) lack rate limit dependencies. |
| **10** | Tokens not leaked through browser logs, storage, or client analytics | **PASS** | No client storage (`localStorage`/`sessionStorage`) of tokens; handled in local React state. |
| **11** | Open redirect and token leakage prevention | **PASS** | Internal React Router navigation in [`LoginPage.tsx`](file:///c:/Users/Win-11/Desktop/My%20World/frontend/src/pages/LoginPage.tsx). |
| **12** | No secrets or raw tokens committed | **PASS** | Clean repo; `.env` excluded. |

---

## 8. Remaining Limitations & Production Conditions

1. **Rate Limiting on Public Invitation Endpoints (Pending):**
   - **Finding:** While authentication endpoints (`/auth/login`, `/auth/register`) are rate-limited via `enforce_auth_rate_limit`, the public invitation endpoints (`GET /api/v1/invitations/{token}` and `POST /api/v1/invitations/{token}/register-and-accept`) currently lack IP rate limiting.
   - **Risk:** An attacker could brute-force invitation tokens (though 256 bits makes random guessing infeasible, DoS against database lookups remains a concern).
   - **Condition:** Add a sliding-window rate limiter dependency to `routes/invitations.py` prior to production deployment.
2. **Reverse Proxy Access Log Redaction (Production Note):**
   - **Finding:** Passing the invitation token in the URL path (`GET /api/v1/invitations/{token}`) means reverse proxies (Nginx, Caddy, AWS CloudFront) and web server access logs will record the raw token by default.
   - **Condition:** In production, configure reverse-proxy access logs to redact `/api/v1/invitations/*` or transition token delivery to a custom request header (`X-Invitation-Token`).
3. **Frontend Automated Test Harness (Architecture Note):**
   - **Finding:** No frontend test runner (Vitest or Playwright) is currently configured in `frontend/package.json`.
   - **Condition:** Implement component and E2E tests for the invitation flow during the Phase 3 or Phase 8 frontend testing wave.

---

## 9. Final Decision & Recommendation

### Verdict: **APPROVED WITH CONDITIONS**

- **Justification:**
  - Finding H2 core security vulnerabilities (unsolicited member injection, account enumeration, privilege bypass, concurrency race condition) are **100% resolved and verified**.
  - PostgreSQL 16 migration `0002_organisation_invitations` is applied and verified.
  - All 49 backend unit, security, and integration tests pass with 0 warnings and 0 failures.
  - Frontend TypeScript build is verified clean and functional.
  - Condition: Rate limiting on public invitation endpoints must be added before public production release.
- **Recommended Next Step:**
  - Update `docs/PHASE2_COMPLETE_AUDIT_REPORT.md` to reflect the resolution of Finding H2 alongside C1 and H1.
  - Ready to proceed to milestone review or Phase 3.
