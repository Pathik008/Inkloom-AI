# Inkloom AI — Phase 2 Finding H1 Verification Report: PostgreSQL 16 + pgvector

**Date:** 2026-11-08
**Scope:** Phase 2 Finding H1 Remediation & Live Database Verification (PostgreSQL 16 + pgvector)
**Status:** FULLY IMPLEMENTED, LIVE VERIFIED & APPROVED

---

## 1. Original Audit Finding (H1)

> **Audit Finding H1 (High Severity):**
> *"PostgreSQL 16 and pgvector have never been tested against a live database instance. The application currently silently falls back to SQLite when PostgreSQL is unavailable. Alembic migrations were redirected to SQLite even when `DATABASE_URL` explicitly specified PostgreSQL."*

---

## 2. Live Environment Details

The live container environment was successfully spun up, configured, and verified:

- **Container Name:** `inkloom-postgres-pgvector`
- **Docker Image:** `pgvector/pgvector:pg16`
- **Container ID:** `3f3c1c440538`
- **Status:** Healthy (`Up`, healthy)
- **Port Mapping:** `0.0.0.0:5432->5432/tcp`, `[::]:5432->5432/tcp`
- **PostgreSQL Server Version:** `16.15 (Debian 16.15-1.pgdg120+1)` (server version num: `160015`)
- **pgvector Extension Version:** `0.8.7`
- **Driver:** Python `psycopg` (v3.3.8 binary) using SQLAlchemy 2.1.8 (`postgresql+psycopg://`)
- **Docker Persistent Volume:** `inkloom_pgdata` mounted to `/var/lib/postgresql/data`

---

## 3. Schema & Migration Status

- **Alembic Version:** `0001_phase2_auth_rbac` applied directly to PostgreSQL.
- **Alembic Drift Check (`alembic check`):** `No new upgrade operations detected.`
- **Verified Tables (7 Application Tables + 1 Migration Catalog):**
  1. `users`
  2. `organisations`
  3. `roles`
  4. `permissions`
  5. `role_permissions`
  6. `organisation_memberships`
  7. `revoked_tokens`
  8. `alembic_version`
- **Seeded RBAC Data:**
  - 4 Roles: `ADMIN`, `BRAND_MANAGER`, `CONTENT_CREATOR`, `REVIEWER`.
  - 10 Permissions: `users:read`, `users:manage`, `organisation:manage`, `brand:read`, `brand:manage`, `content:create`, `content:edit`, `content:review`, `approval:decide`, `audit:read`.
  - 22 Role-Permission mappings properly linked.
- **Schema Persistence:** Confirmed schema, tables, and seeded records survive Docker container restarts via `inkloom_pgdata` volume.

---

## 4. Verification of Elimination of Silent Fallback

1. **Application Settings (`backend/app/core/config.py`):**
   - Removed automatic fallback: `ALLOW_SQLITE_DEV_FALLBACK: bool = False`.
   - Production validation: Added `validate_production_database_security` model validator. In `production` or `staging`, the application strictly refuses to start if `ALLOW_SQLITE_DEV_FALLBACK` is `True`, or if `POSTGRES_PASSWORD` matches the development default (`inkloom_dev_password_change_me`), or if `DATABASE_URL` contains development credentials.
2. **Database Engine (`backend/app/database/__init__.py`):**
   - `_resolve_active_database_uri()` strictly returns the configured PostgreSQL URL when `DATABASE_URL` is set or default settings are used.
   - If PostgreSQL is unreachable on port 5432, it does not silently redirect to SQLite; it raises a clear connection error.
3. **Alembic Configuration (`backend/alembic/env.py`):**
   - Generates DDL strictly against the target dialect (`PostgresqlImpl`).
   - Does not divert to SQLite when `DATABASE_URL` specifies PostgreSQL.

---

## 5. Foreign Key & Unique Constraint Verification

Inspection of `backend/tests/test_postgres_integration.py` revealed that the original `test_postgres_foreign_key_and_unique_constraints` only tested foreign key violations and did not actually execute a unique constraint test.

The test suite was updated and expanded:
1. **Foreign Key Enforcement:**
   - Attempting to insert an organisation referencing a non-existent `created_by` user UUID raises `sqlalchemy.exc.IntegrityError` (`violates foreign key constraint "organisations_created_by_fkey"`).
   - Transaction is rolled back cleanly.
2. **Unique Constraint Enforcement:**
   - Attempting to insert a duplicate user email raises `IntegrityError` (`violates unique constraint "ix_users_email"`).
   - Dedicated test `test_postgres_unique_constraint_enforcement` creates an owner user, creates an organisation with `test_slug`, then attempts to insert a second organisation with the exact same `slug`.
   - Confirms `IntegrityError` (`violates unique constraint "ix_organisations_slug"`).
   - Safe transaction rollback is executed and temporary test records are deleted in reverse foreign-key dependency order without touching any existing data.
3. **psycopg Connection Pool ResourceWarning Fix:**
   - Corrected `_can_connect_to_postgres()` in `backend/tests/test_postgres_integration.py` to ensure `engine.dispose()` is executed inside a `finally:` block.
   - Completely eliminated the unraisable `ResourceWarning: <psycopg.Connection> was deleted while still open` under pytest strict mode (`-W error`).

---

## 6. Vector Operations & Similarity Verification

- Created table with column `embedding vector(3)`.
- Inserted 3-dimensional embeddings for testing.
- Executed Cosine Distance query (`<=>`):
  ```sql
  SELECT id, content, embedding <=> '[0.1, 0.2, 0.3]' AS cosine_dist
  FROM test_pgvector_embeddings
  ORDER BY cosine_dist ASC LIMIT 1;
  ```
- Result: Distance to identical vector was `< 0.0001` (`0.0`), validating vector math on PostgreSQL 16.
- Temporary test table dropped cleanly post-verification.

---

## 7. Credential & Environment Protection

- **Root `.gitignore`:** Confirmed that `.env`, `.env.local`, `.env.*.local`, `backend/.env`, and `frontend/.env` are strictly excluded from version control.
- **`.env.example`:** Only contains documentation and secure placeholder variables, never live passwords or keys.
- **Production Safety:** Production environments fail fast if the default development password is used.
- **C1 JWT Secret Fix:** Fully preserved; all 8 secret and token validation tests pass cleanly.

---

## 8. Automated Test Results Summary

Full backend test suite executed under strict warning mode (`pytest -v -W error`):

```text
backend/tests/test_auth_and_rbac.py::test_1_successful_user_registration PASSED [  3%]
backend/tests/test_auth_and_rbac.py::test_2_duplicate_email_registration_rejection PASSED [  6%]
backend/tests/test_auth_and_rbac.py::test_3_successful_login PASSED      [  9%]
backend/tests/test_auth_and_rbac.py::test_4_incorrect_password_rejection PASSED [ 12%]
backend/tests/test_auth_and_rbac.py::test_5_disabled_user_rejection PASSED [ 15%]
backend/tests/test_auth_and_rbac.py::test_6_invalid_expired_and_revoked_jwt_rejection PASSED [ 18%]
backend/tests/test_auth_and_rbac.py::test_7_authenticated_auth_me PASSED [ 21%]
backend/tests/test_auth_and_rbac.py::test_8_unauthenticated_protected_endpoint_rejection PASSED [ 24%]
backend/tests/test_auth_and_rbac.py::test_9_organisation_creation PASSED [ 27%]
backend/tests/test_auth_and_rbac.py::test_10_organisation_membership_validation PASSED [ 30%]
backend/tests/test_auth_and_rbac.py::test_11_admin_permission_checks PASSED [ 33%]
backend/tests/test_auth_and_rbac.py::test_12_brand_manager_permission_checks PASSED [ 36%]
backend/tests/test_auth_and_rbac.py::test_13_content_creator_permission_checks PASSED [ 39%]
backend/tests/test_auth_and_rbac.py::test_14_reviewer_permission_checks PASSED [ 42%]
backend/tests/test_auth_and_rbac.py::test_15_cross_organisation_access_rejection PASSED [ 45%]
backend/tests/test_auth_and_rbac.py::test_16_user_cannot_change_own_role_without_permission PASSED [ 48%]
backend/tests/test_auth_and_rbac.py::test_17_last_active_admin_cannot_be_removed_or_demoted PASSED [ 51%]
backend/tests/test_health.py::test_root_health_endpoint PASSED           [ 54%]
backend/tests/test_health.py::test_api_v1_health_endpoint PASSED         [ 57%]
backend/tests/test_health.py::test_cors_preflight_headers PASSED         [ 60%]
backend/tests/test_jwt_secret_security.py::test_settings_fails_when_secret_key_is_missing PASSED [ 63%]
backend/tests/test_jwt_secret_security.py::test_settings_fails_when_secret_key_is_empty PASSED [ 66%]
backend/tests/test_jwt_secret_security.py::test_settings_fails_when_secret_key_is_too_short PASSED [ 69%]
backend/tests/test_jwt_secret_security.py::test_settings_fails_for_known_insecure_defaults PASSED [ 72%]
backend/tests/test_jwt_secret_security.py::test_settings_succeeds_with_strong_secret PASSED [ 75%]
backend/tests/test_jwt_secret_security.py::test_token_signed_with_old_insecure_default_is_rejected PASSED [ 78%]
backend/tests/test_jwt_secret_security.py::test_settings_fails_in_production_with_default_postgres_password PASSED [ 81%]
backend/tests/test_jwt_secret_security.py::test_settings_fails_in_production_with_sqlite_fallback PASSED [ 84%]
backend/tests/test_postgres_integration.py::test_postgres_version_is_16_or_higher PASSED [ 87%]
backend/tests/test_postgres_integration.py::test_pgvector_extension_is_active PASSED [ 90%]
backend/tests/test_postgres_integration.py::test_pgvector_column_creation_and_similarity_search PASSED [ 93%]
backend/tests/test_postgres_integration.py::test_postgres_foreign_key_and_unique_constraints PASSED [ 96%]
backend/tests/test_postgres_integration.py::test_postgres_unique_constraint_enforcement PASSED [100%]

============================= 33 passed in 4.36s ==============================
```

- **Total Backend Tests:** 33
- **Passed:** 33
- **Failed:** 0
- **Skipped:** 0
- **Warnings / Unraisable Exceptions:** 0 (all warnings treated as errors via `-W error`)

---

## 9. Final Finding H1 Remediation Verdict

| Audit Requirement | Live Verification Status | Evidence |
| :--- | :---: | :--- |
| PostgreSQL 16 Running | **PASS** | PostgreSQL 16.15 live container `inkloom-postgres-pgvector` running & healthy. |
| pgvector Extension Active | **PASS** | Version 0.8.7 confirmed active in `pg_extension`. Cosine similarity search (`<=>`) verified. |
| Zero Silent Fallback | **PASS** | Application & Alembic strictly connect to PostgreSQL; fails fast if offline without switching to SQLite. |
| Schema & Migrations Applied | **PASS** | Migration `0001_phase2_auth_rbac` applied. 7 application tables + `alembic_version` confirmed. |
| Foreign Key & Unique Constraints | **PASS** | Strictly enforced by PostgreSQL; dedicated tests verify `IntegrityError` and transaction rollback. |
| Data Persistence | **PASS** | Docker persistent volume `inkloom_pgdata` persists tables and seed data across container restart. |
| Production Password Hardening | **PASS** | Insecure development passwords and SQLite fallbacks strictly rejected when `APP_ENV` is production/staging. |
| Secret & Credential Exclusion | **PASS** | `.env` and `.env.*` excluded in `.gitignore`; `.env.example` contains only placeholders. |
| C1 JWT Fix Preserved | **PASS** | All JWT secret validation and forged token rejection tests pass. |
| Automated Test Suite | **PASS** | 33 passed, 0 failed, 0 skipped with zero warnings under `-W error`. |

### Final Finding H1 Approval Verdict: **APPROVED**
Finding H1 is completely resolved and verified against the live PostgreSQL 16 + pgvector environment.
