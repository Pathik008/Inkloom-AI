# Inkloom AI — API Contract Specification

## 1. Overview & Conventions

- **Base URL (Local Development)**: `http://localhost:8000`
- **Versioned API Prefix**: `/api/v1`
- **Content-Type**: `application/json`
- **Authentication**: `Authorization: Bearer <jwt_access_token>`
- **Tenant Context Resolution**:
  - Path-scoped endpoints (`/api/v1/organisations/{organisation_id}...`) validate that the authenticated user has an `ACTIVE` membership in `{organisation_id}` via `get_path_tenant_context`.
  - Context-aware endpoints (`/api/v1/auth/me`) accept an optional `X-Organisation-ID: <uuid>` header and validate active membership before resolving `active_role` and `active_permissions`.
  - Cross-tenant access or invalid organisation membership always returns `403 Forbidden` to prevent IDOR enumeration.
- **Timestamps**: ISO-8601 UTC strings (`YYYY-MM-DDTHH:MM:SS.ffffffZ`).
- **Identifiers**: UUID v4 strings across all domain entities.

### Standard Error Response Envelope
```json
{
  "detail": "Human-readable explanation of the validation, authentication, or permission error"
}
```

---

## 2. System Endpoints (Phase 1 — Implemented)

### 2.1 Root & Versioned Health Check
- **Method & Path**: `GET /health` and `GET /api/v1/health`
- **Authentication**: Public
- **Response Status**: `200 OK`
- **Response Schema (`HealthResponse`)**:
```json
{
  "status": "healthy",
  "service": "Inkloom AI",
  "version": "0.1.0",
  "environment": "development",
  "database_status": "connected (PostgreSQL + pgvector)",
  "database_connected": true,
  "pgvector_target_dimension": 1024,
  "timestamp": "2026-11-08T10:50:00.000000Z"
}
```
> **Database Note**: **PostgreSQL 16 + `pgvector`** is the primary and intended production database. When running locally in `development` mode on a host where Docker/PostgreSQL (`localhost:5432`) is offline, the backend automatically uses a local SQLite development fallback (`sqlite:///./inkloom_dev.db`) and explicitly reports `"database_status": "connected (SQLite dev fallback; PostgreSQL+pgvector port 5432 offline)"`.

---

## 3. Authentication Endpoints (Phase 2 — Implemented)

### 3.1 Register User & Initial Organisation
- **Method & Path**: `POST /api/v1/auth/register`
- **Authentication**: Public (Rate-limited)
- **Purpose**: Atomically creates a new `User` (Argon2id hashed password), an initial `Organisation` (with unique URL slug), and an `ACTIVE` `OrganisationMembership` with the `ADMIN` role.
- **Request Schema (`RegisterRequest`, `extra="forbid"`)**:
```json
{
  "full_name": "Aarav Sharma",
  "email": "aarav@company.com",
  "password": "StrongPassword123",
  "confirm_password": "StrongPassword123",
  "organisation_name": "Acme Consumer Brands",
  "organisation_description": "Global marketing compliance workspace"
}
```
- **Responses**:
  - `201 Created`: Returns `AuthTokenResponse`
  - `409 Conflict`: Email address already registered
  - `422 Unprocessable Entity`: Password strength, mismatch, or field validation error
  - `429 Too Many Requests`: Rate limit exceeded

### 3.2 Login User
- **Method & Path**: `POST /api/v1/auth/login`
- **Authentication**: Public (Rate-limited)
- **Request Schema (`LoginRequest`, `extra="forbid"`)**:
```json
{
  "email": "aarav@company.com",
  "password": "StrongPassword123"
}
```
- **Response (`200 OK` — `AuthTokenResponse`)**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_at": "2026-11-09T10:50:00Z",
  "user": {
    "id": "b1a7c820-6f2d-4c88-8b10-335a9a7d9e01",
    "full_name": "Aarav Sharma",
    "email": "aarav@company.com",
    "is_active": true,
    "is_verified": true,
    "created_at": "2026-11-08T10:50:00Z",
    "memberships": [
      {
        "membership_id": "2c8d94d2-8a42-498c-9242-81c92c15d001",
        "organisation": {
          "id": "e4c3f550-221a-4b11-9c22-119b2e8a0002",
          "name": "Acme Consumer Brands",
          "slug": "acme-consumer-brands",
          "description": "Global marketing compliance workspace",
          "created_by": "b1a7c820-6f2d-4c88-8b10-335a9a7d9e01",
          "created_at": "2026-11-08T10:50:00Z",
          "updated_at": "2026-11-08T10:50:00Z"
        },
        "role": "ADMIN",
        "permissions": [
          "approval:decide",
          "audit:read",
          "brand:manage",
          "brand:read",
          "content:create",
          "content:edit",
          "content:review",
          "organisation:manage",
          "users:manage",
          "users:read"
        ],
        "status": "ACTIVE",
        "joined_at": "2026-11-08T10:50:00Z"
      }
    ],
    "active_organisation_id": "e4c3f550-221a-4b11-9c22-119b2e8a0002",
    "active_role": "ADMIN",
    "active_permissions": [
      "approval:decide",
      "audit:read",
      "brand:manage",
      "brand:read",
      "content:create",
      "content:edit",
      "content:review",
      "organisation:manage",
      "users:manage",
      "users:read"
    ]
  }
}
```
- **Error Responses**:
  - `401 Unauthorized`: Invalid email or password
  - `403 Forbidden`: User account is disabled (`is_active == false`)
  - `429 Too Many Requests`: Rate limit exceeded

### 3.3 Logout & Revoke Access Token
- **Method & Path**: `POST /api/v1/auth/logout`
- **Authentication**: `Bearer <jwt_access_token>`
- **Purpose**: Immediately persists the token's `jti` claim into `revoked_tokens` so any subsequent use of that token is rejected with `401 Unauthorized`.
- **Response (`200 OK` — `LogoutResponse`)**:
```json
{
  "message": "Successfully logged out and revoked access token.",
  "revoked_jti": "9f21a104-5f93-4e4b-88a7-6372940f91a2"
}
```

### 3.4 Current Authenticated User Profile
- **Method & Path**: `GET /api/v1/auth/me`
- **Authentication**: `Bearer <jwt_access_token>`
- **Optional Header**: `X-Organisation-ID: <uuid>` (validated against active user memberships)
- **Responses**:
  - `200 OK`: Returns `CurrentUserResponse`
  - `401 Unauthorized`: Missing, invalid, expired, or revoked token
  - `403 Forbidden`: Disabled account or unauthorised `X-Organisation-ID`

---

## 4. Organisation & Membership Endpoints (Phase 2 — Implemented)

### 4.1 Create Organisation
- **Method & Path**: `POST /api/v1/organisations`
- **Authentication**: `Bearer <jwt_access_token>`
- **Request Schema (`OrganisationCreateRequest`, `extra="forbid"`)**:
```json
{
  "name": "Second Brand Workspace",
  "description": "Regional division"
}
```
- **Response (`201 Created` — `OrganisationDetailResponse`)**:
```json
{
  "id": "83a91c11-1122-4334-9988-776655443322",
  "name": "Second Brand Workspace",
  "slug": "second-brand-workspace",
  "description": "Regional division",
  "created_by": "b1a7c820-6f2d-4c88-8b10-335a9a7d9e01",
  "created_at": "2026-11-08T10:55:00Z",
  "updated_at": "2026-11-08T10:55:00Z",
  "current_user_role": "ADMIN",
  "current_user_permissions": ["..."],
  "member_count": 1
}
```

### 4.2 List Accessible Organisations
- **Method & Path**: `GET /api/v1/organisations`
- **Authentication**: `Bearer <jwt_access_token>`
- **Response (`200 OK`)**: `List[OrganisationDetailResponse]`

### 4.3 Get Organisation Details
- **Method & Path**: `GET /api/v1/organisations/{organisation_id}`
- **Authentication & Authorisation**: Active member of `{organisation_id}`
- **Responses**: `200 OK` (`OrganisationDetailResponse`) or `403 Forbidden`

### 4.4 Update Organisation Details
- **Method & Path**: `PATCH /api/v1/organisations/{organisation_id}`
- **Authentication & Authorisation**: Active member with `organisation:manage` permission (`ADMIN`)
- **Request Schema (`OrganisationUpdateRequest`, `extra="forbid"`)**:
```json
{
  "name": "Updated Workspace Name",
  "description": "Updated description"
}
```
- **Responses**: `200 OK` (`OrganisationDetailResponse`) or `403 Forbidden`

### 4.5 List Organisation Members
- **Method & Path**: `GET /api/v1/organisations/{organisation_id}/members`
- **Authentication & Authorisation**: Active member with `users:read` permission
- **Response (`200 OK`)**: `List[OrganisationMemberResponse]`

### 4.6 Direct Member Addition (Disabled / Deprecated for Security)
- **Method & Path**: `POST /api/v1/organisations/{organisation_id}/members`
- **Authentication & Authorisation**: Active member with `users:manage` permission (`ADMIN`)
- **Status**: **Deprecated / Disabled**. Direct injection without recipient consent is prohibited to prevent account enumeration, unsolicited membership enrollment, and privilege assignment without audit trails.
- **Request Schema (`MemberAddRequest`, `extra="forbid"`)**: Accepted for backward compatibility validation, but rejected by policy.
- **Response**: `400 Bad Request`
```json
{
  "detail": "Direct member addition without explicit invitation acceptance is disabled for security. Use POST /api/v1/organisations/{organisation_id}/invitations to invite team members."
}
```

### 4.7 Create Organisation Invitation
- **Method & Path**: `POST /api/v1/organisations/{organisation_id}/invitations`
- **Authentication & Authorisation**: `Bearer <jwt_access_token>` with `users:manage` permission in `{organisation_id}` (`ADMIN`)
- **Purpose**: Issues a cryptographically secure, single-use invitation. Generates a 256-bit URL-safe random token, stores **only** its SHA-256 hash in PostgreSQL, and returns the raw token and URL once for delivery.
- **Account Enumeration Protection**: Returns `201 Created` with identical schema and timing regardless of whether the recipient email already has an Inkloom account.
- **Request Schema (`InvitationCreateRequest`, `extra="forbid"`)**:
```json
{
  "email": "colleague@company.com",
  "role": "CONTENT_CREATOR"
}
```
- **Response (`201 Created` — `InvitationCreateResponse`)**:
```json
{
  "id": "9d1b7123-4e89-4a92-bf31-01f1295b9c20",
  "organisation_id": "83a91c11-1122-4334-9988-776655443322",
  "email": "colleague@company.com",
  "role": "CONTENT_CREATOR",
  "status": "PENDING",
  "expires_at": "2026-11-15T10:55:00Z",
  "created_at": "2026-11-08T10:55:00Z",
  "invitation_token": "q5W_9xVz1...",
  "invitation_url": "/accept-invitation?token=q5W_9xVz1...",
  "delivery_status": "token_generated_for_manual_dispatch",
  "message": "Invitation created. In development/testing, copy the invitation link."
}
```
- **Error Responses**:
  - `400 Bad Request`: Invalid role specified or validation failure
  - `403 Forbidden`: Caller lacks `users:manage` or is not an active member in `{organisation_id}`
  - `409 Conflict`: User is already an `ACTIVE` member of `{organisation_id}`

### 4.8 List Organisation Invitations
- **Method & Path**: `GET /api/v1/organisations/{organisation_id}/invitations`
- **Authentication & Authorisation**: `Bearer <jwt_access_token>` with `users:read` permission in `{organisation_id}`
- **Security Guarantee**: Never returns raw tokens or token hashes. Only public metadata, status, timestamps, and inviting user brief are returned.
- **Response (`200 OK`)**: `List[InvitationResponse]`
```json
[
  {
    "id": "9d1b7123-4e89-4a92-bf31-01f1295b9c20",
    "organisation_id": "83a91c11-1122-4334-9988-776655443322",
    "email": "colleague@company.com",
    "role": "CONTENT_CREATOR",
    "status": "PENDING",
    "expires_at": "2026-11-15T10:55:00Z",
    "created_at": "2026-11-08T10:55:00Z",
    "accepted_at": null,
    "revoked_at": null,
    "invited_by": {
      "id": "b1a7c820-6f2d-4c88-8b10-335a9a7d9e01",
      "full_name": "Aarav Sharma",
      "email": "aarav@company.com",
      "is_active": true
    }
  }
]
```

### 4.9 Revoke Organisation Invitation
- **Method & Path**: `DELETE /api/v1/organisations/{organisation_id}/invitations/{invitation_id}`
- **Authentication & Authorisation**: `Bearer <jwt_access_token>` with `users:manage` permission in `{organisation_id}` (`ADMIN`)
- **Purpose**: Marks a `PENDING` invitation as `REVOKED`, immediately preventing any subsequent preview or acceptance.
- **Responses**:
  - `204 No Content`: Invitation successfully revoked
  - `400 Bad Request`: Invitation is not in `PENDING` status (e.g., already `ACCEPTED`, `REVOKED`, or `EXPIRED`)
  - `403 Forbidden`: Caller lacks `users:manage` or belongs to another organisation
  - `404 Not Found`: Invitation not found in this organisation

### 4.10 Update Member Role
- **Method & Path**: `PATCH /api/v1/organisations/{organisation_id}/members/{membership_id}`
- **Authentication & Authorisation**: Active member with `users:manage` permission (`ADMIN`)
- **Request Schema (`MemberRoleUpdateRequest`, `extra="forbid"`)**:
```json
{
  "role": "REVIEWER"
}
```
- **Responses**:
  - `200 OK`: `OrganisationMemberResponse`
  - `400 Bad Request`: Attempted to demote the last active `ADMIN` of the organisation
  - `403 Forbidden`: Caller lacks `users:manage` or is not in the organisation
  - `404 Not Found`: Membership not found in this organisation

### 4.11 Remove Organisation Member
- **Method & Path**: `DELETE /api/v1/organisations/{organisation_id}/members/{membership_id}`
- **Authentication & Authorisation**: Active member with `users:manage` permission (`ADMIN`)
- **Responses**:
  - `204 No Content`: Member removed
  - `400 Bad Request`: Attempted to remove the last active `ADMIN` of the organisation
  - `403 Forbidden`: Caller lacks `users:manage` or is not in the organisation
  - `404 Not Found`: Membership not found in this organisation

---

## 5. Invitation Lifecycle & Acceptance Endpoints (Phase 2 — Implemented)

### 5.1 Public Invitation Preview
- **Method & Path**: `GET /api/v1/invitations/{token}`
- **Authentication**: Public
- **Purpose**: Validates the raw token and retrieves safe public metadata for the invitation landing screen (`AcceptInvitationPage`).
- **Security Guarantee**:
  - Token verified via constant-time SHA-256 digest comparison (`hmac.compare_digest`).
  - Returns only safe metadata. Never returns `token_hash` or internal user identifiers.
  - Returns identical `404 Not Found` for invalid tokens or nonexistent hashes.
- **Response (`200 OK` — `InvitationDetailPublic`)**:
```json
{
  "id": "9d1b7123-4e89-4a92-bf31-01f1295b9c20",
  "organisation_name": "Second Brand Workspace",
  "email": "colleague@company.com",
  "role": "CONTENT_CREATOR",
  "expires_at": "2026-11-15T10:55:00Z",
  "status": "PENDING"
}
```
- **Error Responses**:
  - `404 Not Found`: Token not found or invalid
  - `409 Conflict`: Invitation has already been `ACCEPTED`
  - `410 Gone`: Invitation has been `REVOKED` or `EXPIRED`

### 5.2 Authenticated Invitation Acceptance
- **Method & Path**: `POST /api/v1/invitations/{token}/accept`
- **Authentication**: `Bearer <jwt_access_token>`
- **Purpose**: Allows an existing logged-in user to explicitly accept an invitation.
- **Security Enforcements**:
  - **Recipient Matching**: The authenticated user's email **must strictly match** `invitation.email` (case-insensitive). If mismatched, returns generic `403 Forbidden` (`"You are not authorised to accept this invitation."`) without disclosing account details.
  - **Concurrency & Atomicity**: Obtains PostgreSQL row-level lock (`with_for_update(of=OrganisationInvitation).execution_options(populate_existing=True)`). Verifies `PENDING` status, adds or activates `OrganisationMembership`, and marks invitation `ACCEPTED` in a single ACID transaction. Concurrent race attempts are rejected with `409 Conflict`.
- **Response (`200 OK` — `InvitationAcceptanceResponse`)**:
```json
{
  "message": "Successfully joined Second Brand Workspace as CONTENT_CREATOR.",
  "organisation_id": "83a91c11-1122-4334-9988-776655443322",
  "organisation_name": "Second Brand Workspace",
  "role": "CONTENT_CREATOR",
  "joined_at": "2026-11-08T11:00:00Z"
}
```
- **Error Responses**:
  - `401 Unauthorized`: Missing or invalid bearer token
  - `403 Forbidden`: Authenticated user email does not match invitation recipient email
  - `404 Not Found`: Invalid invitation token
  - `409 Conflict`: Invitation already accepted or user already an active member
  - `410 Gone`: Invitation revoked or expired

### 5.3 Registration & Invitation Acceptance
- **Method & Path**: `POST /api/v1/invitations/{token}/register-and-accept`
- **Authentication**: Public
- **Purpose**: Provisions a brand-new user account and accepts the invitation atomically in one step.
- **Security Enforcements**:
  - **Email Binding**: User email is strictly bound to `invitation.email` stored on the backend; the client cannot specify or alter the email.
  - **Account Collision**: If an account with `invitation.email` already exists, returns `400 Bad Request` instructing the user to log in and accept instead of silently overwriting.
  - **Password Strength**: Minimum 8 characters, requiring at least one letter and one number, hashed using Argon2id.
  - **Concurrency & Atomicity**: Row-level locking on `OrganisationInvitation` ensures only one registration/acceptance can succeed for the token.
- **Request Schema (`InvitationRegisterAndAcceptRequest`, `extra="forbid"`)**:
```json
{
  "full_name": "Siddharth Verma",
  "password": "StrongPassword123",
  "confirm_password": "StrongPassword123"
}
```
- **Response (`201 Created` — `AuthTokenResponse`)**:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_at": "2026-11-09T11:00:00Z",
  "user": {
    "id": "e7b1a201-4455-6677-8899-aabbccddeeff",
    "full_name": "Siddharth Verma",
    "email": "colleague@company.com",
    "is_active": true,
    "is_verified": true,
    "created_at": "2026-11-08T11:00:00Z",
    "memberships": [
      {
        "membership_id": "f8c2b302-5566-7788-9900-bbccddeeff00",
        "organisation": {
          "id": "83a91c11-1122-4334-9988-776655443322",
          "name": "Second Brand Workspace",
          "slug": "second-brand-workspace",
          "description": "Regional division",
          "created_by": "b1a7c820-6f2d-4c88-8b10-335a9a7d9e01",
          "created_at": "2026-11-08T10:55:00Z",
          "updated_at": "2026-11-08T10:55:00Z"
        },
        "role": "CONTENT_CREATOR",
        "permissions": [
          "brand:read",
          "content:create",
          "content:edit"
        ],
        "status": "ACTIVE",
        "joined_at": "2026-11-08T11:00:00Z"
      }
    ],
    "active_organisation_id": "83a91c11-1122-4334-9988-776655443322",
    "active_role": "CONTENT_CREATOR",
    "active_permissions": [
      "brand:read",
      "content:create",
      "content:edit"
    ]
  }
}
```
- **Error Responses**:
  - `400 Bad Request`: An account with this email already exists, or validation failure (passwords mismatch / too weak)
  - `404 Not Found`: Invalid invitation token
  - `409 Conflict`: Invitation already accepted
  - `410 Gone`: Invitation revoked or expired

---

## 6. Planned API Endpoints Registry (Phases 3–9)

| Module | Endpoint Prefix | Primary Operations | Target Phase |
| :--- | :--- | :--- | :--- |
| **Brand Kits & Versioning** | `/api/v1/brand-kits` | `POST /`, `GET /`, `GET /{kit_id}`, `POST /{kit_id}/versions`, `POST /{kit_id}/versions/{ver_id}/publish` | Phase 3 |
| **Brand Knowledge (Facts & Rules)** | `/api/v1/brand-kits/{kit_id}/versions/{ver_id}` | `POST /facts`, `GET /facts`, `POST /rules`, `GET /rules`, `POST /assets`, `POST /documents` | Phase 3 |
| **Content Ingestion & Revisions** | `/api/v1/content` | `POST /`, `POST /upload`, `GET /`, `GET /{content_id}`, `POST /{content_id}/revisions`, `GET /{content_id}/revisions` | Phase 4 |
| **Compliance Reviews & Findings** | `/api/v1/reviews` | `POST /run`, `GET /{review_id}`, `GET /{review_id}/findings`, `POST /{review_id}/apply-suggestion` | Phases 5–7 |
| **Human Approval Workflow** | `/api/v1/approvals` | `POST /submit`, `GET /inbox`, `POST /{request_id}/decision` (`APPROVE`, `REJECT`, `REQUEST_REVISION`) | Phase 8 |
| **Audit Logs** | `/api/v1/audit-logs` | `GET /` (paginated, tenant-isolated, filterable by action, actor, resource) | Phase 8 |
| **Analytics & Dashboard** | `/api/v1/analytics` | `GET /dashboard-summary`, `GET /trends`, `GET /violations-breakdown`, `GET /export` | Phase 9 |
