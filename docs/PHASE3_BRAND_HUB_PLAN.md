# Inkloom AI — Phase 3 Architecture & Implementation Plan: Brand Hub (Final Implementation-Ready Revision)

**Document Version:** 3.0 (Final Implementation-Readiness Specification)  
**Target Milestone:** Phase 3 — Brand Hub (Persistent Multi-Tenant Versioned Brand Kits)  
**Baseline Checkpoint:** `0a57f49` (Phase 2 Approved Milestone)  
**Status:** CONDITIONALLY APPROVED — FINAL INTEGRATION DETAILS RESOLVED (AWAITING IMPLEMENTATION AUTHORISATION)

---

## 1. Executive Summary & Architectural Principles

The **Brand Hub** is the authoritative source of brand truth for Inkloom AI's compliance and content review engine. Every content generation or compliance review workflow in subsequent phases must evaluate content against an **immutable, published `BrandKitVersion`** belonging to the active tenant (`Organisation`).

### Core Architectural Guarantees
1. **Triple-Layer Published Immutability:** Once a `BrandKitVersion` transitions from `DRAFT` to `PUBLISHED` (or `ARCHIVED`), its identity, facts, compliance rules, assets, and guideline document binaries cannot be modified or deleted through the API, ORM service layer, or direct SQL updates/deletes (enforced via PostgreSQL triggers with an explicit column-level allowlist for asynchronous document parsing telemetry).
2. **Defense-in-Depth Tenant Read & Write Isolation:**
   - **Mandatory `TenantContext` on Every Read & Write:** Composite foreign keys enforce relational integrity on writes and joins, but **do not independently filter `SELECT` queries**. Every Brand Hub read, list, download, audit query, and write operation requires an authenticated `TenantContext` resolved via `get_path_tenant_context` / `require_permission` (`backend/app/api/deps.py:165-184`) and executes through mandatory tenant-scoped query helpers that append `WHERE <table>.organisation_id = :ctx_org_id`.
   - **Composite Tenant Foreign Keys:** Every child entity carries `organisation_id` and enforces a **composite foreign key** `(parent_id, organisation_id)` referencing the parent table's `(id, organisation_id)` unique key, making cross-organisation parent/child linking structurally impossible in PostgreSQL.
3. **Deterministic Version Concurrency & Lifecycle (`DRAFT -> PUBLISHED -> ARCHIVED`):** Version creation, publishing, and archiving lock the parent `BrandKit` and target `BrandKitVersion` rows (`SELECT ... FOR UPDATE` with `populate_existing=True`), enforce `UNIQUE (brand_kit_id, version_number)` and a partial unique index `WHERE status = 'DRAFT'` (at most one active working draft per Brand Kit), and forbid restoring `ARCHIVED` versions (reusing an archived version requires cloning a new `DRAFT` version $N+1$).
4. **Hardened File Upload & Transactional Storage Consistency:** Strict magic-byte signature verification (never trusting `Content-Type` headers alone), filename canonicalization, UUID storage keys, SVG script/event-handler sanitization, streaming SHA-256 checksums, two-phase staging-to-permanent promotion (`storage/.staging/{uuid}.part` $\rightarrow$ `os.replace`), rollback compensation, and reference-counted file retention across cloned versions.
5. **Phase 2 RBAC & Audit Continuity:** Seamless integration with existing `PermissionCode.BRAND_READ` (`brand:read`) and `PermissionCode.BRAND_MANAGE` (`brand:manage`) already seeded in `0001_phase2_auth_rbac.py`, verified idempotently in migration `0003_phase3_brand_hub`, and structured audit logging into `audit_logs`.

---

## 2. Phase 2 RBAC Compatibility & Migration `0003` Specification

### 2.1 Inspection of Existing Phase 2 RBAC Implementation
Direct inspection of the Phase 2 codebase confirms the following exact implementation:

1. **Permission Definitions (`backend/app/models/__init__.py:47-58`):**
   `PermissionCode` (a `str, Enum`) already defines both Brand Hub permissions:
   ```python
   class PermissionCode(str, Enum):
       ORG_READ = "org:read"
       ORG_MANAGE = "org:manage"
       USERS_READ = "users:read"
       USERS_MANAGE = "users:manage"
       BRAND_READ = "brand:read"       # Line 51
       BRAND_MANAGE = "brand:manage"   # Line 52
       CONTENT_CREATE = "content:create"
       CONTENT_READ = "content:read"
       REVIEW_RUN = "review:run"
       REVIEW_APPROVE = "review:approve"
       AUDIT_READ = "audit:read"
   ```
2. **Role-Permission Matrix (`backend/app/models/__init__.py:73-105`):**
   `ROLE_PERMISSION_MATRIX` already maps `brand:read` and `brand:manage` across the four built-in `RoleCode` values:
   - `RoleCode.ADMIN` (`admin`): includes `PermissionCode.BRAND_READ` and `PermissionCode.BRAND_MANAGE`.
   - `RoleCode.BRAND_MANAGER` (`brand_manager`): includes `PermissionCode.BRAND_READ` and `PermissionCode.BRAND_MANAGE`.
   - `RoleCode.CONTENT_CREATOR` (`content_creator`): includes `PermissionCode.BRAND_READ` (read-only).
   - `RoleCode.REVIEWER` (`reviewer`): includes `PermissionCode.BRAND_READ` (read-only).
3. **Database Seeding (`backend/alembic/versions/0001_phase2_auth_rbac.py:180-221` & `seed_roles_and_permissions`):**
   Migration `0001_phase2_auth_rbac` already inserts `("brand:read", "View Brand Kits, approved facts, and compliance rules")` and `("brand:manage", "Create, update, and publish Brand Kits and rules")` into `permissions` and binds them in `role_permissions` using `ON CONFLICT DO NOTHING`.
4. **Organisation Membership & RBAC Dependencies (`backend/app/api/deps.py:104-184`):**
   - `resolve_organisation_membership(db, user, organisation_id)` (lines 114–162) queries `OrganisationMembership` joined with `Organisation` and eagerly loads `OrganisationMembership.role -> Role.permissions`, rejecting missing/inactive memberships or inactive organisations with `403 Forbidden` and returning a `TenantContext(user, organisation, membership, role_code, permissions)`.
   - `get_path_tenant_context(organisation_id: uuid.UUID = Path(...), ...)` (lines 165–171) resolves `TenantContext` directly from the `{organisation_id}` URL path parameter.
   - `require_permission(required_permission: str)` (lines 174–184) wraps `get_path_tenant_context` and raises `403 Forbidden ("Permission '{required_permission}' is required for this operation.")` if `required_permission not in context.permissions`.

### 2.2 How Migration `0003_phase3_brand_hub` Handles `brand:read` and `brand:manage`
Because `0001_phase2_auth_rbac` already created and mapped `brand:read` and `brand:manage`, migration `0003_phase3_brand_hub` **must not** drop, rename, replace, or weaken any existing permissions or role mappings. Instead, `0003_phase3_brand_hub` executes an **idempotent verification & upsert step** during `upgrade()`:

```sql
-- Idempotently ensure brand:read and brand:manage exist in permissions
INSERT INTO permissions (id, code, description)
VALUES
  (gen_random_uuid(), 'brand:read', 'View Brand Kits, approved facts, and compliance rules'),
  (gen_random_uuid(), 'brand:manage', 'Create, update, and publish Brand Kits and rules')
ON CONFLICT (code) DO NOTHING;

-- Idempotently ensure role_permissions mappings match ROLE_PERMISSION_MATRIX
INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.code = 'brand:read'
WHERE r.code IN ('admin', 'brand_manager', 'content_creator', 'reviewer')
ON CONFLICT (role_id, permission_id) DO NOTHING;

INSERT INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON p.code = 'brand:manage'
WHERE r.code IN ('admin', 'brand_manager')
ON CONFLICT (role_id, permission_id) DO NOTHING;
```

- **Downgrade Safety (`downgrade()` in `0003`):** `downgrade()` drops only the Phase 3 tables (`brand_guideline_documents`, `brand_assets`, `brand_compliance_rules`, `brand_approved_facts`, `brand_kit_versions`, `brand_kits`) and their Phase 3 trigger functions. It **never** deletes rows from `permissions` or `role_permissions`, preserving full Phase 2 RBAC state.

### 2.3 Endpoint Permission Matrix

| Operation Category | Required Dependency | Permitted Roles | Denied Roles (`403 Forbidden`) |
|---|---|---|---|
| Read Brand Kits, Versions, Facts, Rules, Assets, Documents | `Depends(require_permission(PermissionCode.BRAND_READ))` | `admin`, `brand_manager`, `content_creator`, `reviewer` | Non-members, `INVITED`/`SUSPENDED` members |
| Download Brand Asset or Guideline Document Binary | `Depends(require_permission(PermissionCode.BRAND_READ))` | `admin`, `brand_manager`, `content_creator`, `reviewer` | Non-members, `INVITED`/`SUSPENDED` members |
| Create/Edit Draft, Manage Facts/Rules, Upload/Delete Files, Publish, Archive | `Depends(require_permission(PermissionCode.BRAND_MANAGE))` | `admin`, `brand_manager` | `content_creator`, `reviewer`, non-members |
| Read Brand Hub Audit Events | `Depends(require_permission(PermissionCode.AUDIT_READ))` | `admin` | `brand_manager`, `content_creator`, `reviewer`, non-members |

---

## 3. Tenant Read & Write Isolation Architecture

### 3.1 Why Composite Foreign Keys Are Necessary But Insufficient for Reads
Composite foreign keys (`FOREIGN KEY (parent_id, organisation_id) REFERENCES parent(id, organisation_id)`) guarantee at the database level that a child row in Tenant A can **never** be inserted or updated to reference a parent row in Tenant B. However, composite foreign keys **do not filter `SELECT` queries**. A naive query such as `db.get(BrandKit, kit_id)` or `select(BrandAsset).where(BrandAsset.id == asset_id)` would return Tenant A's record to Tenant B if `organisation_id` were omitted from the `WHERE` clause.

### 3.2 Mandatory `TenantContext` Enforcement for Every Read and Write Operation
To prevent cross-tenant reads, updates, deletes, and file downloads, Phase 3 enforces the following **non-negotiable query architecture**:

1. **Path-Scoped `TenantContext` Injection on Every Route:**
   Every Brand Hub route is mounted under `/api/v1/organisations/{organisation_id}/brand-kits...` and injects `context: TenantContext = Depends(require_permission(...))`. No route accepts `organisation_id` from a request body or query parameter.
2. **Ban on Unscoped `db.get()`:**
   Direct calls to `db.get(Model, entity_id)` are **prohibited** in `brand_service.py` and `brand_kits.py`.
3. **Mandatory Tenant-Scoped Loader Helpers in `brand_service.py`:**
   All database reads, updates, deletes, and downloads must resolve target entities through dedicated helpers that require `context: TenantContext` (or `org_id: uuid.UUID`) and include `Model.organisation_id == org_id` in every `WHERE` clause:

```python
def _get_brand_kit_or_404(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    for_update: bool = False,
) -> BrandKit:
    stmt = select(BrandKit).where(
        BrandKit.id == brand_kit_id,
        BrandKit.organisation_id == organisation_id,
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    kit = db.scalars(stmt).first()
    if not kit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Brand Kit not found in this organisation.",
        )
    return kit


def _get_version_or_404(
    db: Session,
    *,
    organisation_id: uuid.UUID,
    brand_kit_id: uuid.UUID,
    version_id: uuid.UUID,
    for_update: bool = False,
) -> BrandKitVersion:
    stmt = select(BrandKitVersion).where(
        BrandKitVersion.id == version_id,
        BrandKitVersion.brand_kit_id == brand_kit_id,
        BrandKitVersion.organisation_id == organisation_id,
    )
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    version = db.scalars(stmt).first()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Brand Kit version not found in this organisation.",
        )
    return version


def _get_child_entity_or_404(
    db: Session,
    model_cls: type[T],
    *,
    organisation_id: uuid.UUID,
    brand_kit_version_id: uuid.UUID,
    entity_id: uuid.UUID,
) -> T:
    stmt = select(model_cls).where(
        model_cls.id == entity_id,
        model_cls.brand_kit_version_id == brand_kit_version_id,
        model_cls.organisation_id == organisation_id,
    )
    entity = db.scalars(stmt).first()
    if not entity:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Requested brand resource not found in this organisation.",
        )
    return entity
```

4. **Uniform `404 Not Found` on Cross-Tenant Resource Probes:**
   When an authenticated member of Organisation B requests a `brand_kit_id`, `version_id`, `fact_id`, `rule_id`, `asset_id`, or `doc_id` belonging to Organisation A under `/api/v1/organisations/{org_B_id}/...`, the tenant-scoped `WHERE organisation_id = :org_B_id` predicate returns `None` and raises `404 Not Found` (preventing cross-tenant UUID enumeration). When a user who is **not** a member of Organisation A requests `/api/v1/organisations/{org_A_id}/...`, `resolve_organisation_membership` raises `403 Forbidden` before any Brand Hub query runs.
5. **Asset & Document Download Isolation:**
   Binary download endpoints (`GET .../assets/{asset_id}/download` and `GET .../documents/{doc_id}/download`) first verify the parent `BrandKit` and `BrandKitVersion` via `_get_version_or_404(db, organisation_id=context.organisation.id, ...)` and then load the `BrandAsset` / `BrandGuidelineDocument` via `_get_child_entity_or_404(db, ..., organisation_id=context.organisation.id, ...)`. Furthermore, before opening the file on disk, the storage service verifies that the resolved canonical filesystem path resides strictly inside `{STORAGE_ROOT}/{context.organisation.id}/brand_kits/{brand_kit_id}/`.

### 3.3 Composite Tenant Foreign Keys in PostgreSQL
Every Brand Hub table stores `organisation_id UUID NOT NULL` and exposes a composite unique constraint `UNIQUE (id, organisation_id)` so child tables can bind to it via composite foreign keys:

```
organisations (id)
  └── brand_kits (id, organisation_id)  [UNIQUE (id, organisation_id)]
        ├── active_version_id -> FK (active_version_id, id, organisation_id)
        │     REFERENCES brand_kit_versions (id, brand_kit_id, organisation_id)
        └── brand_kit_versions (id, brand_kit_id, organisation_id)
              [UNIQUE (id, brand_kit_id, organisation_id)]
              [UNIQUE (id, organisation_id)]
              ├── brand_approved_facts (brand_kit_version_id, organisation_id)
              ├── brand_compliance_rules (brand_kit_version_id, organisation_id)
              ├── brand_assets (brand_kit_version_id, organisation_id)
              └── brand_guideline_documents (brand_kit_version_id, organisation_id)
```

### 3.4 PostgreSQL Row-Level Security (RLS) Evaluation & Connection-Pooling Safety
- **Why Naive RLS is Dangerous with Connection Pooling:**
  SQLAlchemy's default `QueuePool` reuses PostgreSQL connections across requests. Executing session-scoped `SET app.current_organisation_id = '...'` leaks tenant state to subsequent requests if a connection is returned to the pool without `RESET ALL`, or if a background task shares the connection. Additionally, if the PostgreSQL connection user is the table owner (or has `BYPASSRLS`), RLS policies are silently bypassed unless `FORCE ROW LEVEL SECURITY` is enabled.
- **Architectural Decision for Phase 3:**
  1. **Primary Mandatory Control (Enforced in Phase 3):** Application-level `TenantContext` dependency injection + mandatory tenant-scoped query helpers (`WHERE organisation_id = :org_id`) + Database-level Composite Tenant Foreign Keys (`(parent_id, organisation_id)`). This matches Phase 2 (`OrganisationMembership`, `OrganisationInvitation`, `AuditLog`) and has zero connection-pool state hazards.
  2. **Safe Pattern if PostgreSQL RLS is Enabled (Transaction-Scoped `SET LOCAL`):**
     If PostgreSQL RLS is layered in the future, it **must never** use session-level `SET`. It must use `SET LOCAL app.current_organisation_id = :org_id` inside `get_path_tenant_context` (which PostgreSQL automatically scopes to the current transaction and clears on `COMMIT` or `ROLLBACK`) paired with `current_setting('app.current_organisation_id', true)::uuid`. Because the application connects as the schema owner in standard single-role deployments, Phase 3 does not rely on RLS for tenant isolation and instead enforces explicit `organisation_id` predicates verified by dedicated cross-tenant integration tests.

---

## 4. Deterministic Version Lifecycle & Active Version Semantics

### 4.1 State Machine (`DRAFT -> PUBLISHED -> ARCHIVED`)

```
                     ┌────────────────────────────────────────────────────────┐
                     │  Clones new DRAFT (version_number = MAX + 1) from      │
                     │  active PUBLISHED version or selected source version   │
                     ▼                                                        │
[Create Brand Kit] ──► [ DRAFT (v1) ] ──(Publish)──► [ PUBLISHED (v1) ] ──────┼──(Archive or Superseded)──► [ ARCHIVED (v1) ]
                         │  ▲                          │                      │                               (Terminal State)
                         └──┘                          └──────────────────────┴──────────────────────────────►(Clone into vN+1)
                     (Mutable in place)               (Strictly Immutable)                                   (Strictly Immutable)
```

### 4.2 Explicit Lifecycle Answers & Invariants

1. **Can an `ARCHIVED` version ever be restored to `PUBLISHED` or `DRAFT`?**
   - **No.** `ARCHIVED` is a **terminal state**. Both the service layer (`brand_service.py`) and the PostgreSQL trigger (`trg_enforce_brand_kit_version_immutability`) strictly forbid transitioning `ARCHIVED -> PUBLISHED` or `ARCHIVED -> DRAFT` (`ERROR: ERRCODE P0003 - Cannot transition BrandKitVersion from ARCHIVED to ...`).
   - **How to reuse an archived version:** An `ADMIN` or `BRAND_MANAGER` invokes `POST /api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions` with `{"source_version_id": "<archived_version_uuid>"}`. This creates a brand-new mutable `DRAFT` version ($N + 1$) deep-cloned from the archived version, preserving an unbroken, append-only audit and version history.

2. **How does `brand_kits.active_version_id` change during publishing?**
   - Every `BrandKit` has at most **one** active `PUBLISHED` version at any point in time, referenced by `brand_kits.active_version_id`.
   - When `DRAFT` version $V_{\text{new}}$ is published (`POST .../versions/{ver_id}/publish`):
     1. The transaction acquires row locks (`SELECT ... FOR UPDATE` with `populate_existing=True`) on the `BrandKit` row and the target `BrandKitVersion` row.
     2. If `brand_kit.active_version_id` is currently non-null (pointing to a previously published version $V_{\text{old}}$), the transaction locks $V_{\text{old}}$ (`FOR UPDATE`) and **atomically transitions $V_{\text{old}}$ from `PUBLISHED` to `ARCHIVED`** (setting `V_old.status = 'ARCHIVED'`, `V_old.archived_at = now`, `V_old.archived_by_user_id = current_user.id`).
     3. The transaction transitions $V_{\text{new}}$ from `DRAFT` to `PUBLISHED` (`V_new.status = 'PUBLISHED'`, `V_new.published_at = now`, `V_new.published_by_user_id = current_user.id`).
     4. The transaction updates `brand_kit.active_version_id = V_new.id` and `brand_kit.updated_at = now`.
   - **Result:** At any instant, a `BrandKit` has at most one `PUBLISHED` version (which is also `brand_kit.active_version_id`), at most one `DRAFT` version (enforced by partial unique index `uq_brand_kit_single_draft`), and zero or more historical `ARCHIVED` versions.

3. **What happens when the currently active `PUBLISHED` version is explicitly archived?**
   - When an administrator calls `POST .../versions/{ver_id}/archive` on a `PUBLISHED` version:
     1. The transaction locks `BrandKit` and `BrandKitVersion` (`FOR UPDATE` with `populate_existing=True`).
     2. If `version.status != 'PUBLISHED'`, it raises `409 Conflict` (`"Only PUBLISHED versions can be archived."`).
     3. It transitions `version.status = 'ARCHIVED'`, `version.archived_at = now`, `version.archived_by_user_id = current_user.id`.
     4. If `brand_kit.active_version_id == version.id`, it atomically sets `brand_kit.active_version_id = None`.
   - **Downstream Impact:** When `brand_kit.active_version_id IS NULL`, no new content compliance review can be started against that Brand Kit until a new draft is published; however, all historical compliance reviews that recorded `brand_kit_version_id = version.id` retain full read access to that immutable `ARCHIVED` snapshot.

4. **How is a new `DRAFT` cloned?**
   - When `POST /api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions` is called:
     1. The service locks the parent `BrandKit` row (`SELECT ... FOR UPDATE` with `populate_existing=True`).
     2. It checks whether a `DRAFT` version already exists for this `brand_kit_id`. If so, it raises `409 Conflict` (`"A draft version already exists for this Brand Kit."`).
     3. **Source Version Selection:**
        - If `payload.source_version_id` is provided, it loads that version via `_get_version_or_404(db, organisation_id=org_id, brand_kit_id=kit_id, version_id=payload.source_version_id)` (guaranteeing same Brand Kit and same Organisation).
        - Otherwise, if `brand_kit.active_version_id` is set, it uses the active `PUBLISHED` version as the clone source.
        - Otherwise, it selects the highest `version_number` version for that `brand_kit_id` (if any exists).
     4. **Next Version Number Calculation:** `next_ver = COALESCE(MAX(version_number), 0) + 1` under the `BrandKit` row lock.
     5. **Deep Copy of Snapshot Data:**
        - Copies identity columns (`brand_voice_summary`, `target_audience`, `dos_and_donts`, `logos_json`, `colours_json`, `typography_json`).
        - Clones all `BrandApprovedFact` rows where `approval_status == 'APPROVED'` (assigning new `id`s and pointing to the new `DRAFT` `brand_kit_version_id`).
        - Clones all `BrandComplianceRule` rows (assigning new `id`s and pointing to the new `DRAFT` `brand_kit_version_id`).
        - Clones all `BrandAsset` and `BrandGuidelineDocument` metadata rows (assigning new `id`s and pointing to the new `DRAFT` `brand_kit_version_id` while referencing the same immutable content-addressed/UUID `storage_path` and `file_sha256`, and preserving `parsing_status` / `raw_text_content` on already-parsed documents).

5. **How are concurrent draft creation and concurrent publishing requests handled?**
   - **Concurrent Draft Creation:** Both transactions attempt `SELECT ... FROM brand_kits WHERE id = :kit_id AND organisation_id = :org_id FOR UPDATE`. Transaction B blocks until Transaction A commits. When Transaction B resumes, `populate_existing=True` refreshes state, the check for an existing `DRAFT` sees Transaction A's newly committed `DRAFT`, and Transaction B cleanly returns `409 Conflict`. Even if bypassed, `uq_brand_kit_single_draft` (`UNIQUE (brand_kit_id) WHERE status = 'DRAFT'`) and `uq_brand_kit_version_number` (`UNIQUE (brand_kit_id, version_number)`) catch any race condition and map `IntegrityError` to `409 Conflict`.
   - **Concurrent Publishing:** Both transactions acquire `FOR UPDATE` on `BrandKit` and `BrandKitVersion` in deterministic order (`BrandKit` first, then `BrandKitVersion`). Transaction A transitions the version from `DRAFT` to `PUBLISHED` and commits. Transaction B unblocks, refreshes the row (`populate_existing=True`), sees `version.status == 'PUBLISHED'`, and immediately raises `409 Conflict ("Brand Kit version is already PUBLISHED and cannot be published again.")`.

### 4.3 Pre-Publish Validation Gates
Before a `DRAFT` version can transition to `PUBLISHED`, `publish_brand_kit_version()` validates:
1. `version.status == VersionStatus.DRAFT` (else `409 Conflict`).
2. Required identity fields are present (`brand_voice_summary` is non-empty, or at least one colour/typography/rule/fact is configured; if completely empty, raises `422 Unprocessable Entity`).
3. **Zero Unapproved Facts Gate:** Queries `SELECT COUNT(*) FROM brand_approved_facts WHERE brand_kit_version_id = :ver_id AND approval_status != 'APPROVED'`. If count > 0, raises `422 Unprocessable Entity` (`"Cannot publish Brand Kit version while unapproved or rejected facts exist. Approve or delete pending facts before publishing."`).
4. **Zero Failed/Pending Document Gate (Configurable or Explicit):** Verifies all attached `BrandAsset` and `BrandGuidelineDocument` rows have valid `file_sha256` and exist on disk.

---

## 5. Triple-Layer Immutability & Database-Trigger Allowlist for Document Processing

### 5.1 Layer 1 & Layer 2: API Design and Service Guard (`assert_version_is_draft`)
Every mutation function in `backend/app/services/brand_service.py` (updating identity fields, creating/updating/deleting facts or rules, uploading/deleting assets or documents) begins by locking the parent `BrandKitVersion` row (`FOR UPDATE` with `populate_existing=True`) and calling:

```python
def assert_version_is_draft(version: BrandKitVersion) -> None:
    if version.status != VersionStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Brand Kit version {version.version_number} is {version.status.value} "
                "and is strictly immutable. Create a new draft version to make changes."
            ),
        )
```

### 5.2 Layer 3: PostgreSQL Triggers & Exact Column Allowlist for `brand_guideline_documents`
Migration `0003_phase3_brand_hub` installs three PostgreSQL `BEFORE UPDATE OR DELETE` / `BEFORE INSERT OR UPDATE OR DELETE` trigger functions:

#### Trigger 1: `fn_enforce_brand_kit_version_immutability()` on `brand_kit_versions`
- **Blocks `DELETE`** when `OLD.status IN ('PUBLISHED', 'ARCHIVED')` (`ERRCODE 'P0001'`).
- **Blocks `UPDATE` of any content or identity column** when `OLD.status IN ('PUBLISHED', 'ARCHIVED')`:
  Specifically verifies that `id`, `brand_kit_id`, `organisation_id`, `version_number`, `created_From_version_id`, `brand_voice_summary`, `target_audience`, `dos_and_donts`, `logos_json`, `colours_json`, `typography_json`, `created_by_user_id`, `created_at`, `published_by_user_id`, and `published_at` are unchanged (`IS NOT DISTINCT FROM`).
- **Strictly Enforces State Transitions:**
  - If `OLD.status = 'PUBLISHED'`, the only permitted `UPDATE` is `NEW.status = 'ARCHIVED'` with `NEW.archived_at IS NOT NULL` and all other columns unchanged.
  - If `OLD.status = 'ARCHIVED'`, **all** `UPDATE` operations are rejected (`ERRCODE 'P0003'`).

#### Trigger 2: `fn_enforce_brand_child_immutability()` on `brand_approved_facts`, `brand_compliance_rules`, and `brand_assets`
- Queries `SELECT status FROM brand_kit_versions WHERE id = target_version_id`.
- If parent `status != 'DRAFT'`, **rejects all `INSERT`, `UPDATE`, and `DELETE` operations unconditionally** (`ERRCODE 'P0002'`).

#### Trigger 3: `fn_enforce_guideline_doc_immutability()` on `brand_guideline_documents` (With Explicit Column Allowlist)
When a `BrandKitVersion` is published, asynchronous document parsing or Phase 4 pgvector embedding may update processing telemetry on an already-uploaded `brand_guideline_documents` row. However, the document's binary identity, ownership, version association, and cryptographic hash must remain **strictly immutable**.

| Column Category | Exact Column Names on `brand_guideline_documents` | Permitted When Parent `status != 'DRAFT'`? |
|---|---|---|
| **Strictly Locked Identity & Ownership Columns** | `id`, `brand_kit_version_id`, `organisation_id`, `title`, `document_category`, `original_filename`, `stored_filename`, `storage_backend`, `storage_path`, `mime_type`, `file_size_bytes`, `file_sha256`, `uploaded_by_user_id`, `created_at` | **NO** (Trigger raises `P0002` on any modification; `INSERT` and `DELETE` are also completely blocked) |
| **Allowlisted Processing Telemetry Columns** | `parsing_status`, `parse_attempt_count`, `last_error_code`, `last_error_message`, `page_count`, `raw_text_content`, `embedding_model`, `embedding_model_version`, `parsed_at`, `embedded_at` | **YES** (Permitted on `UPDATE` **only** if every locked column above satisfies `NEW.<col> IS NOT DISTINCT FROM OLD.<col>`) |

Exact PostgreSQL PL/pgSQL trigger definition for `brand_guideline_documents`:

```sql
CREATE OR REPLACE FUNCTION fn_enforce_guideline_doc_immutability()
RETURNS TRIGGER AS $$
DECLARE
    parent_status VARCHAR(20);
    target_version_id UUID;
BEGIN
    IF TG_OP = 'DELETE' THEN
        target_version_id := OLD.brand_kit_version_id;
    ELSE
        target_version_id := NEW.brand_kit_version_id;
    END IF;

    SELECT status INTO parent_status
    FROM brand_kit_versions
    WHERE id = target_version_id;

    IF parent_status IS NOT NULL AND parent_status IN ('PUBLISHED', 'ARCHIVED') THEN
        -- Block INSERT and DELETE completely on non-DRAFT versions
        IF TG_OP IN ('INSERT', 'DELETE') THEN
            RAISE EXCEPTION 'Cannot % brand_guideline_documents belonging to a % BrandKitVersion (id=%)',
                TG_OP, parent_status, target_version_id
                USING ERRCODE = 'P0002';
        END IF;

        -- On UPDATE, verify thatOld and New locked identity/file/ownership columns are identical
        IF TG_OP = 'UPDATE' THEN
            IF (
                NEW.id IS DISTINCT FROM OLD.id OR
                NEW.brand_kit_version_id IS DISTINCT FROM OLD.brand_kit_version_id OR
                NEW.organisation_id IS DISTINCT FROM OLD.organisation_id OR
                NEW.title IS DISTINCT FROM OLD.title OR
                NEW.document_category IS DISTINCT FROM OLD.document_category OR
                NEW.original_filename IS DISTINCT FROM OLD.original_filename OR
                NEW.stored_filename IS DISTINCT FROM OLD.stored_filename OR
                NEW.storage_backend IS DISTINCT FROM OLD.storage_backend OR
                NEW.storage_path IS DISTINCT FROM OLD.storage_path OR
                NEW.mime_type IS DISTINCT FROM OLD.mime_type OR
                NEW.file_size_bytes IS DISTINCT FROM OLD.file_size_bytes OR
                NEW.file_sha256 IS DISTINCT FROM OLD.file_sha256 OR
                NEW.uploaded_by_user_id IS DISTINCT FROM OLD.uploaded_by_user_id OR
                NEW.created_at IS DISTINCT FROM OLD.created_at
            ) THEN
                RAISE EXCEPTION 'Cannot modify immutable file or ownership columns on brand_guideline_documents for % BrandKitVersion (id=%)',
                    parent_status, target_version_id
                    USING ERRCODE = 'P0002';
            END IF;
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_enforce_guideline_doc_immutability
BEFORE INSERT OR UPDATE OR DELETE ON brand_guideline_documents
FOR EACH ROW EXECUTE FUNCTION fn_enforce_guideline_doc_immutability();
```

---

## 6. File Upload Security & Database/Filesystem Consistency Protocol

### 6.1 Upload Validation & Sanitization Pipeline (`backend/app/services/storage_service.py`)
1. **Extension & Magic-Byte Allowlist:**
   - **Brand Assets (`logo_primary`, `logo_secondary`, `icon`, `font_file`, `imagery_sample`):**
     - `.png`: magic bytes `\x89PNG\r\n\x1a\n` (`image/png`) — max `10 MB`
     - `.jpg` / `.jpeg`: magic bytes `\xff\xd8\xff` (`image/jpeg`) — max `10 MB`
     - `.webp`: magic bytes `RIFF....WEBP` (`image/webp`) — max `10 MB`
     - `.svg`: validated via `defusedxml` (no `<!DOCTYPE>`, `<!ENTITY>`, `<script>`, `<foreignObject>`, `onload`/`onerror` `on*` attributes, or `javascript:`/`data:` URIs) (`image/svg+xml`) — max `2 MB`
     - `.ttf` (`\x00\x01\x00\x00`), `.otf` (`OTTO`), `.woff` (`wOFF`), `.woff2` (`wOF2`) — max `15 MB`
   - **Brand Guideline Documents (`brand_book`, `style_guide`, `tone_guide`, `legal_disclaimer`, `product_sheet`):**
     - `.pdf`: magic bytes `%PDF-` (`application/pdf`) — max `25 MB`
     - `.docx`: ZIP header `PK\x03\x04` containing `word/document.xml` with zero `..` path entries — max `25 MB`
     - `.txt` / `.md`: strict UTF-8 decoding with zero `\x00` null bytes — max `5 MB`
2. **Filename Canonicalization & Storage Path Construction:**
   - Display filename (`original_filename`): strip directory components (`PurePath(raw).name`), reject null bytes or `..`, strip control characters, limit to 255 chars.
   - Disk filename (`stored_filename`): `{uuid4().hex}.{validated_ext}` (user filenames are **never** used in filesystem paths).
   - Relative storage path (`storage_path`): `{organisation_id}/brand_kits/{brand_kit_id}/{assets|documents}/{uuid4().hex}.{ext}`.
   - Path containment assertion: `resolved_target.resolve().is_relative_to(STORAGE_ROOT.resolve())` is checked before every write, read, or unlink.

### 6.2 Two-Phase Staging, Atomic Promotion & Rollback Compensation
To prevent partial writes, orphaned files on failed DB commits, or database rows pointing to missing files:

1. **Phase 1 — Stream to Staging (`storage/.staging/{staging_uuid}.part`):**
   - Stream upload in `64 KB` chunks to `{STORAGE_ROOT}/.staging/{staging_uuid}.part`.
   - Enforce byte limit during streaming; if exceeded, close and unlink the `.part` file immediately and raise `413 Content Too Large`.
   - Compute `hashlib.sha256()` incrementally while streaming.
   - Validate magic bytes / SVG safety / DOCX structure on the staged file. If invalid, unlink `.part` and raise `415 Unsupported Media Type` or `422 Unprocessable Entity`.
   - Flush and `os.fsync(fd)` the staging file.
2. **Phase 2 — Database Transaction & Atomic Promotion (`os.replace`):**
   - Acquire `FOR UPDATE` lock on the target `DRAFT` `BrandKitVersion` row.
   - Insert the `BrandAsset` or `BrandGuidelineDocument` row and call `db.flush()` so all DB constraints (`FK`, `CHECK`, triggers) are validated before touching the final storage directory.
   - Promote the staged file atomically into its final destination using `os.replace(staging_path, final_path)` (atomic on POSIX and Windows NTFS within the same volume).
   - Call `db.commit()`.
3. **Phase 3 — Database Commit Failure Recovery (Compensation):**
   - If `db.flush()` or `db.commit()` raises any exception:
     - Execute `db.rollback()`.
     - In the `except` block, safely unlink both `staging_path` (if still present) and `final_path` (`Path.unlink(missing_ok=True)`), ensuring **zero orphaned files** remain on disk when a database transaction fails.

### 6.3 Reference-Counted File Deletion Across Cloned Versions
Because cloning a `BrandKitVersion` (`v1 -> v2`) clones `BrandAsset` and `BrandGuidelineDocument` metadata rows that reference the same underlying immutable `storage_path`, deleting an asset or document from a `DRAFT` version (`v2`) **must not** delete the physical file on disk if `v1` (or any other version) still references that `storage_path`!

**Mandatory Reference-Count Deletion Protocol:**
1. Verify parent `BrandKitVersion` is `DRAFT` (`assert_version_is_draft`).
2. Delete the `BrandAsset` (or `BrandGuidelineDocument`) row for the `DRAFT` version and `db.flush()`.
3. Query remaining references inside the transaction:
   ```python
   remaining_refs = db.scalar(
       select(func.count())
       .select_from(BrandAsset)
       .where(
           BrandAsset.organisation_id == organisation_id,
           BrandAsset.storage_path == target_storage_path,
       )
   )
   ```
4. Commit the database transaction (`db.commit()`).
5. **Only if `remaining_refs == 0`:** unlink the physical file from disk (`final_path.unlink(missing_ok=True)`). If `remaining_refs > 0`, the physical file is preserved intact for the historical `PUBLISHED`/`ARCHIVED` versions that still reference it.

### 6.4 Missing-File Detection & Stale Staging Cleanup
- **On Download (`GET .../download`):**
  1. Resolve metadata row via tenant-scoped query (`_get_child_entity_or_404`).
  2. Verify `final_path.is_file()`. If the file is missing on disk, log a high-severity structured warning and raise `404 Not Found` (`"Stored file binary is missing from storage."`) rather than an unhandled `500 FileNotFoundError`.
  3. Verify on-disk file size matches `file_size_bytes` and stream response with `Content-Disposition: attachment; filename="..."` and `X-Content-Type-Options: nosniff`.
- **On Version Clone & Publish:**
  - Before cloning or publishing a version, verify that every referenced `BrandAsset` and `BrandGuidelineDocument` file exists on disk (`final_path.is_file()`). If a referenced file is missing on disk during publish, raise `422 Unprocessable Entity` identifying the corrupted/missing asset or document.
- **Retry-Safe Stale Staging Cleanup (`cleanup_stale_staging_files()`):**
  - Any `.part` file in `{STORAGE_ROOT}/.staging/` with `mtime < now - 3600 seconds` (1 hour) is unlinked using `Path.unlink(missing_ok=True)` with `OSError` suppression so concurrent cleanup runs are idempotent and retry-safe.

---

## 7. Complete PostgreSQL Schema Specification (Migration `0003_phase3_brand_hub`)

### 7.1 Table 1: `brand_kits`
| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | `PRIMARY KEY` | Unique Brand Kit identifier |
| `organisation_id` | `UUID` | `NOT NULL`, `FK -> organisations.id ON DELETE CASCADE` | Owning tenant |
| `name` | `VARCHAR(150)` | `NOT NULL` | Display name (e.g., `"Global Corporate Brand"`) |
| `slug` | `VARCHAR(120)` | `NOT NULL` | URL-safe slug unique within organisation |
| `description` | `TEXT` | `NULL` | High-level summary of the Brand Kit's purpose |
| `is_default` | `BOOLEAN` | `NOT NULL DEFAULT FALSE` | Whether this is the default kit for the organisation |
| `active_version_id` | `UUID` | `NULL` | Points to currently active `PUBLISHED` `brand_kit_versions.id` |
| `created_by_user_id` | `UUID` | `NULL`, `FK -> users.id ON DELETE SET NULL` | Creator user reference |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL DEFAULT now()` | Creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL DEFAULT now()` | Last metadata update timestamp |

**Indexes & Constraints on `brand_kits`:**
- `UNIQUE (id, organisation_id)` — target for composite tenant foreign keys.
- `UNIQUE (organisation_id, slug)` (`uq_brand_kits_org_slug`).
- Partial unique index `uq_brand_kits_single_default_per_org` on `(organisation_id) WHERE is_default = true`.
- Deferred composite foreign key `fk_brand_kits_active_version_tenant`: `FOREIGN KEY (active_version_id, id, organisation_id) REFERENCES brand_kit_versions(id, brand_kit_id, organisation_id) DEFERRABLE INITIALLY DEFERRED`.

### 7.2 Table 2: `brand_kit_versions`
| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `UUID` | `PRIMARY KEY` | Version snapshot UUID |
| `brand_kit_id` | `UUID` | `NOT NULL` | Parent Brand Kit |
| `organisation_id` | `UUID` | `NOT NULL` | Denormalised tenant ID |
| `version_number` | `INTEGER` | `NOT NULL CHECK (version_number >= 1)` | Monotonically increasing integer (`1, 2, 3...`) |
| `status` | `VARCHAR(20)` | `NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'PUBLISHED', 'ARCHIVED'))` | Lifecycle status |
| `change_summary` | `TEXT` | `NULL` | Release notes for this version |
| `created_from_version_id` | `UUID` | `NULL`, `FK -> brand_kit_versions.id ON DELETE SET NULL` | Source version if cloned |
| `brand_voice_summary` | `TEXT` | `NULL` | Tone, persona, and stylistic posture |
| `target_audience` | `TEXT` | `NULL` | Intended audience profile |
| `dos_and_donts` | `JSONB` | `NOT NULL DEFAULT '{"dos": [], "donts": []}'::jsonb` | Structured writing do's and don'ts |
| `logos_json` | `JSONB` | `NOT NULL DEFAULT '[]'::jsonb` | Structured logo usage rules & asset refs |
| `colours_json` | `JSONB` | `NOT NULL DEFAULT '[]'::jsonb` | Validated hex/RGB/CMYK colour palette |
| `typography_json` | `JSONB` | `NOT NULL DEFAULT '[]'::jsonb` | Font families, weights, hierarchy roles |
| `created_by_user_id` | `UUID` | `NULL`, `FK -> users.id ON DELETE SET NULL` | Author of draft |
| `published_by_user_id` | `UUID` | `NULL`, `FK -> users.id ON DELETE SET NULL` | Publisher (`ADMIN` / `BRAND_MANAGER`) |
| `archived_by_user_id` | `UUID` | `NULL`, `FK -> users.id ON DELETE SET NULL` | Archiver (`ADMIN` / `BRAND_MANAGER`) |
| `created_at` | `TIMESTAMPTZ` | `NOT NULL DEFAULT now()` | Draft creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | `NOT NULL DEFAULT now()` | Last draft modification timestamp |
| `published_at` | `TIMESTAMPTZ` | `NULL` | Timestamp when locked as `PUBLISHED` |
| `archived_at` | `TIMESTAMPTZ` | `NULL` | Timestamp when transitioned to `ARCHIVED` |

**Indexes & Constraints on `brand_kit_versions`:**
- `FOREIGN KEY (brand_kit_id, organisation_id) REFERENCES brand_kits(id, organisation_id) ON DELETE CASCADE`.
- `UNIQUE (id, organisation_id)` — composite FK target for child tables.
- `UNIQUE (id, brand_kit_id, organisation_id)` — composite FK target for `brand_kits.active_version_id`.
- `UNIQUE (brand_kit_id, version_number)` (`uq_brand_kit_version_number`).
- Partial unique index `uq_brand_kit_single_draft` on `(brand_kit_id) WHERE status = 'DRAFT'`.
- Partial unique index `uq_brand_kit_single_published` on `(brand_kit_id) WHERE status = 'PUBLISHED'`.

### 7.3 Table 3: `brand_approved_facts`
- `id UUID PRIMARY KEY`
- `brand_kit_version_id UUID NOT NULL`
- `organisation_id UUID NOT NULL`
- `category VARCHAR(80) NOT NULL` (`company_metric`, `product_claim`, `award`, `sustainability`, `legal_boilerplate`, `leadership`, `general`)
- `fact_key VARCHAR(150) NOT NULL`
- `claim_statement TEXT NOT NULL`
- `supporting_evidence TEXT NULL`
- `source_citation VARCHAR(500) NULL`
- `valid_from TIMESTAMPTZ NULL`, `valid_until TIMESTAMPTZ NULL`
- `is_locked BOOLEAN NOT NULL DEFAULT TRUE`
- `approval_status VARCHAR(20) NOT NULL DEFAULT 'APPROVED' CHECK (approval_status IN ('PENDING', 'APPROVED', 'REJECTED'))`
- `approved_by_user_id UUID NULL FK -> users.id ON DELETE SET NULL`
- `approved_at TIMESTAMPTZ NULL`
- `created_by_user_id UUID NULL FK -> users.id ON DELETE SET NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- **Composite FK:** `FOREIGN KEY (brand_kit_version_id, organisation_id) REFERENCES brand_kit_versions(id, organisation_id) ON DELETE CASCADE`
- **Unique Constraint:** `UNIQUE (brand_kit_version_id, fact_key)`

### 7.4 Table 4: `brand_compliance_rules`
- `id UUID PRIMARY KEY`
- `brand_kit_version_id UUID NOT NULL`
- `organisation_id UUID NOT NULL`
- `rule_code VARCHAR(64) NOT NULL`
- `title VARCHAR(200) NOT NULL`
- `description TEXT NOT NULL`
- `category VARCHAR(50) NOT NULL CHECK (category IN ('TONE', 'TERMINOLOGY', 'FORBIDDEN_PHRASE', 'REQUIRED_DISCLAIMER', 'VISUAL_IDENTITY', 'FACTUAL_ALIGNMENT', 'ACCESSIBILITY'))`
- `severity VARCHAR(20) NOT NULL DEFAULT 'HIGH' CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL'))`
- `enforcement_mode VARCHAR(20) NOT NULL DEFAULT 'FLAG' CHECK (enforcement_mode IN ('BLOCK', 'FLAG', 'SUGGEST'))`
- `evaluation_strategy VARCHAR(30) NOT NULL DEFAULT 'HYBRID' CHECK (evaluation_strategy IN ('DETERMINISTIC_REGEX', 'DETERMINISTIC_KEYWORD', 'LLM_SEMANTIC', 'HYBRID'))`
- `rule_config JSONB NOT NULL DEFAULT '{}'::jsonb`
- `is_Enabled BOOLEAN NOT NULL DEFAULT TRUE`
- `sort_order INTEGER NOT NULL DEFAULT 0`
- `created_by_user_id UUID NULL FK -> users.id ON DELETE SET NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- **Composite FK:** `FOREIGN KEY (brand_kit_version_id, organisation_id) REFERENCES brand_kit_versions(id, organisation_id) ON DELETE CASCADE`
- **Unique Constraint:** `UNIQUE (brand_kit_version_id, rule_code)`

### 7.5 Table 5: `brand_assets`
- `id UUID PRIMARY KEY`
- `brand_kit_version_id UUID NOT NULL`
- `organisation_id UUID NOT NULL`
- `asset_type VARCHAR(40) NOT NULL CHECK (asset_type IN ('logo_primary', 'logo_secondary', 'icon', 'font_file', 'imagery_sample'))`
- `display_name VARCHAR(200) NOT NULL`
- `original_filename VARCHAR(255) NOT NULL`
- `stored_filename VARCHAR(255) NOT NULL`
- `storage_backend VARCHAR(30) NOT NULL DEFAULT 'local'`
- `storage_path VARCHAR(512) NOT NULL`
- `mime_type VARCHAR(100) NOT NULL`
- `file_size_bytes BIGINT NOT NULL CHECK (file_size_bytes > 0)`
- `file_sha256 VARCHAR(64) NOT NULL`
- `asset_metadata JSONB NOT NULL DEFAULT '{}'::jsonb`
- `uploaded_by_user_id UUID NULL FK -> users.id ON DELETE SET NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- **Composite FK:** `FOREIGN KEY (brand_kit_version_id, organisation_id) REFERENCES brand_kit_versions(id, organisation_id) ON DELETE CASCADE`

### 7.6 Table 6: `brand_guideline_documents`
- `id UUID PRIMARY KEY`
- `brand_kit_version_id UUID NOT NULL`
- `organisation_id UUID NOT NULL`
- `title VARCHAR(200) NOT NULL`
- `document_category VARCHAR(50) NOT NULL DEFAULT 'brand_book' CHECK (document_category IN ('brand_book', 'style_guide', 'tone_guide', 'legal_disclaimer', 'product_sheet'))`
- `original_filename VARCHAR(255) NOT NULL`
- `stored_filename VARCHAR(255) NOT NULL`
- `storage_backend VARCHAR(30) NOT NULL DEFAULT 'local'`
- `storage_path VARCHAR(512) NOT NULL`
- `mime_type VARCHAR(100) NOT NULL`
- `file_size_bytes BIGINT NOT NULL CHECK (file_size_bytes > 0)`
- `file_sha256 VARCHAR(64) NOT NULL`
- `parsing_status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (parsing_status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED'))`
- `parse_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (parse_attempt_count >= 0)`
- `last_error_code VARCHAR(64) NULL`
- `last_error_message VARCHAR(1000) NULL`
- `page_count INTEGER NULL`
- `raw_text_content TEXT NULL`
- `embedding_model VARCHAR(100) NULL`
- `embedding_model_version VARCHAR(50) NULL`
- `uploaded_by_user_id UUID NULL FK -> users.id ON DELETE SET NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `parsed_at TIMESTAMPTZ NULL`
- `embedded_at TIMESTAMPTZ NULL`
- **Composite FK:** `FOREIGN KEY (brand_kit_version_id, organisation_id) REFERENCES brand_kit_versions(id, organisation_id) ON DELETE CASCADE`

---

## 8. REST API Contract (`/api/v1/organisations/{organisation_id}/brand-kits`)

| Method | Path | Permission | Description |
|---|---|---|---|
| `GET` | `/api/v1/organisations/{org_id}/brand-kits` | `brand:read` | List Brand Kits for organisation (with active & draft version summaries) |
| `POST` | `/api/v1/organisations/{org_id}/brand-kits` | `brand:manage` | Create Brand Kit + initial `DRAFT` Version 1 |
| `GET` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}` | `brand:read` | Get Brand Kit metadata + version history list |
| `PATCH` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}` | `brand:manage` | Update Brand Kit name, description, or `is_default` |
| `POST` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions` | `brand:manage` | Clone new `DRAFT` version ($N+1$) from active/source version |
| `GET` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}` | `brand:read` | Get complete `BrandKitVersion` snapshot (identity, facts, rules, assets, docs) |
| `PATCH` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}` | `brand:manage` | Update identity fields on a `DRAFT` version (`409` if not `DRAFT`) |
| `POST` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/publish` | `brand:manage` | Atomically publish `DRAFT` version, supersede old active version to `ARCHIVED`, set `active_version_id` |
| `POST` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/archive` | `brand:manage` | Atomically archive `PUBLISHED` version and clear `active_version_id` if active |
| `POST` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/facts` | `brand:manage` | Add approved/pending fact to `DRAFT` version (`409` if not `DRAFT`) |
| `PATCH` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/facts/{fact_id}` | `brand:manage` | Update/approve fact on `DRAFT` version (`409` if not `DRAFT`) |
| `DELETE` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/facts/{fact_id}` | `brand:manage` | Delete fact from `DRAFT` version (`409` if not `DRAFT`) |
| `POST` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/rules` | `brand:manage` | Add compliance rule to `DRAFT` version (`409` if not `DRAFT`) |
| `PATCH` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/rules/{rule_id}` | `brand:manage` | Update compliance rule on `DRAFT` version (`409` if not `DRAFT`) |
| `DELETE` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/rules/{rule_id}` | `brand:manage` | Delete compliance rule from `DRAFT` version (`409` if not `DRAFT`) |
| `POST` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/assets` | `brand:manage` | Multipart upload of Brand Asset to `DRAFT` version (`409` if not `DRAFT`) |
| `GET` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/assets/{asset_id}/download` | `brand:read` | Tenant-verified binary download of Brand Asset |
| `DELETE` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/assets/{asset_id}` | `brand:manage` | Reference-counted deletion of Brand Asset from `DRAFT` version |
| `POST` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/documents` | `brand:manage` | Multipart upload + text extraction of Guideline Document on `DRAFT` version |
| `POST` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/documents/{doc_id}/reparse` | `brand:manage` | Retry parsing when `parsing_status == 'FAILED'` |
| `GET` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/documents/{doc_id}/download` | `brand:read` | Tenant-verified binary download of Guideline Document |
| `DELETE` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/versions/{ver_id}/documents/{doc_id}` | `brand:manage` | Reference-counted deletion of Guideline Document from `DRAFT` version |
| `GET` | `/api/v1/organisations/{org_id}/brand-kits/{kit_id}/audit-logs` | `audit:read` | List Brand Hub audit log events scoped to this `organisation_id` and `brand_kit_id` |

---

## 9. Final Acceptance Criteria & Comprehensive Verification Test Plan

The implementation will be verified in `backend/tests/test_brand_hub.py` and `backend/tests/test_postgres_integration.py` against all of the following mandatory test scenarios:

### 9.1 Cross-Tenant Read, Write, Download & Audit Isolation Tests
1. **`test_cross_tenant_brand_kit_read_and_list_blocked`:**
   - Org A creates a Brand Kit (`v1`).
   - User in Org B calls `GET /api/v1/organisations/{org_A_id}/brand-kits` $\rightarrow$ `403 Forbidden`.
   - User in Org B calls `GET /api/v1/organisations/{org_B_id}/brand-kits/{org_A_kit_id}` $\rightarrow$ `404 Not Found`.
   - User in Org B calls `GET /api/v1/organisations/{org_B_id}/brand-kits/{org_A_kit_id}/versions/{org_A_ver_id}` $\rightarrow$ `404 Not Found`.
2. **`test_cross_tenant_updates_and_deletes_blocked`:**
   - User in Org B attempts `PATCH` and `DELETE` against Org A's `brand_kit_id`, `version_id`, `fact_id`, `rule_id`, `asset_id`, and `doc_id` using `/organisations/{org_B_id}/...` $\rightarrow$ all return `404 Not Found` and leave Org A's records untouched.
3. **`test_cross_tenant_asset_and_document_downloads_blocked`:**
   - User in Org B calls `GET /api/v1/organisations/{org_B_id}/brand-kits/{org_A_kit_id}/versions/{org_A_ver_id}/assets/{org_A_asset_id}/download` and `/documents/{org_A_doc_id}/download` $\rightarrow$ `404 Not Found`.
   - User in Org B calls the same URLs under `/organisations/{org_A_id}/...` $\rightarrow$ `403 Forbidden`.
4. **`test_cross_tenant_audit_log_access_blocked`:**
   - Admin of Org B requests `/api/v1/organisations/{org_B_id}/brand-kits/{org_A_kit_id}/audit-logs` $\rightarrow$ `404 Not Found`.
   - Admin of Org B requests `/api/v1/organisations/{org_A_id}/brand-kits/{org_A_kit_id}/audit-logs` $\rightarrow$ `403 Forbidden`.
5. **`test_database_composite_fk_blocks_cross_tenant_child_linking`:**
   - Direct SQL / ORM attempt to insert a `BrandApprovedFact` or `BrandAsset` with `organisation_id = org_B.id` pointing to `brand_kit_version_id = org_A_version.id` fails with PostgreSQL `ForeignKeyViolation`.

### 9.2 Published & Archived Version Immutability & Trigger Allowlist Tests
6. **`test_api_rejects_all_mutations_on_published_and_archived_versions`:**
   - After publishing `v1`, API calls to `PATCH` version identity, `POST/PATCH/DELETE` facts, `POST/PATCH/DELETE` rules, and `POST/DELETE` assets or documents all fail with `409 Conflict`.
7. **`test_postgres_trigger_blocks_direct_sql_mutation_and_deletion_of_published_version`:**
   - Direct SQL `UPDATE brand_kit_versions SET brand_voice_summary = 'tampered' WHERE id = :pub_id` and `DELETE FROM brand_kit_versions WHERE id = :pub_id` fail with PostgreSQL exception (`P0001`).
   - Direct SQL `INSERT`, `UPDATE`, or `DELETE` on `brand_approved_facts`, `brand_compliance_rules`, and `brand_assets` for a `PUBLISHED` version fails with `P0002`.
8. **`test_guideline_document_trigger_allowlist_on_published_version`:**
   - On a `PUBLISHED` version, direct SQL / service update of allowlisted telemetry columns (`parsing_status = 'COMPLETED'`, `raw_text_content = '...'`, `page_count = 4`, `parsed_at = now()`) **succeeds**.
   - On the same `PUBLISHED` version, updating any locked column (`file_sha256`, `storage_path`, `original_filename`, `stored_filename`, `mime_type`, `file_size_bytes`, `organisation_id`, `brand_kit_version_id`, `title`) or executing `DELETE` **fails** with PostgreSQL trigger exception `P0002`.

### 9.3 Version Lifecycle, Active Version & Concurrency Tests
9. **`test_publish_updates_active_version_and_supersedes_previous_published_to_archived`:**
   - Publishing `v1` sets `brand_kit.active_version_id = v1.id` and `v1.status = 'PUBLISHED'`.
   - Cloning `v2` (`DRAFT`) and publishing `v2` atomically transitions `v1.status` to `'ARCHIVED'`, sets `v2.status = 'PUBLISHED'`, and updates `brand_kit.active_version_id = v2.id`.
10. **`test_archive_active_version_clears_active_version_id_and_blocks_restoration`:**
    - Archiving active version `v2` transitions `v2.status = 'ARCHIVED'` and sets `brand_kit.active_version_id = None`.
    - Attempting to re-publish `v2` or restore `v2` to `DRAFT` or `PUBLISHED` via API (`409 Conflict`) or direct SQL (`P0003`) is blocked.
    - Cloning `v3` (`DRAFT`) specifying `source_version_id = v2.id` succeeds and copies `v2`'s snapshot into `v3`.
11. **`test_concurrent_draft_creation_and_concurrent_publishing_protection`:**
    - Concurrent requests to create a new draft on the same `BrandKit` result in exactly one `201 Created` (`version_number = 2`) and one `409 Conflict`.
    - Concurrent requests to publish the same `DRAFT` version result in one `200 OK` and one `409 Conflict`.
12. **`test_publish_blocked_when_unapproved_facts_exist`:**
    - Adding a fact with `approval_status = 'PENDING'` or `'REJECTED'` to a `DRAFT` version and calling `/publish` returns `422 Unprocessable Entity`; approving the fact allows `/publish` to succeed.

### 9.4 File Security & Storage/Database Consistency Tests
13. **`test_invalid_uploads_mime_spoofing_path_traversal_and_malicious_svg_rejected`:**
    - Executable/HTML renamed to `.png` or `.pdf` (magic-byte mismatch) $\rightarrow$ `415 Unsupported Media Type`.
    - SVG containing `<script>`, `onload=`, or `<!ENTITY>` $\rightarrow$ `422 Unprocessable Entity`.
    - Filename `../../etc/passwd.png` is stripped to `passwd.png` for display and stored under a random UUID filename inside the tenant directory.
    - Oversized file $\rightarrow$ `413 Content Too Large` and staging `.part` file is unlinked.
14. **`test_reference_counted_file_deletion_preserves_cloned_version_files`:**
    - Upload asset `A1` to `v1` (`DRAFT`), publish `v1`.
    - Clone `v2` (`DRAFT`) from `v1` (`v2` now has cloned asset row `A2` pointing to the same `storage_path`).
    - Delete `A2` from `v2` (`DRAFT`).
    - Verify `A2` is removed from `v2`, **the physical file remains on disk**, and downloading `A1` from published `v1` still succeeds with matching SHA-256!
    - Upload a brand-new asset `A3` to `v2` (`DRAFT`) and delete `A3` from `v2` (reference count == 0) $\rightarrow$ physical file for `A3` is unlinked from disk.
15. **`test_db_commit_failure_cleans_up_promoted_file_and_missing_file_detected_on_download`:**
    - Simulate a database commit failure during upload $\rightarrow$ verify promoted file is unlinked from disk (zero orphan files).
    - If a file on disk is manually removed, `GET .../download` returns a clean `404 Not Found` instead of `500 Internal Server Error`.

### 9.5 RBAC Enforcement & Migration `0003` Reversibility Tests
16. **`test_rbac_content_creator_and_reviewer_read_only_enforcement`:**
    - `CONTENT_CREATOR` and `REVIEWER` can `GET` Brand Kits, versions, facts, rules, and download assets/documents (`200 OK`), but receive `403 Forbidden` on all `POST`, `PATCH`, `DELETE`, `publish`, and `archive` endpoints, and `403 Forbidden` on `/audit-logs`.
17. **`test_alembic_migration_0003_downgrade_and_upgrade_preserves_phase2_permissions`:**
    - Verify `alembic downgrade 0002_organisation_invitations` followed by `alembic upgrade head` succeeds cleanly without deleting or weakening `brand:read` or `brand:manage` in `permissions` / `role_permissions`.
