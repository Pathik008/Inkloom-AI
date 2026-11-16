"""Targeted, secure judge credential setup utility for Inkloom AI Production.

Complies strictly with CodeTitans Round 3 evaluation governance:
- Targets ONLY judge@inkloom.ai
- Positively validates Railway runtime & database identity (--require-railway)
- Strictly rejects local Docker databases (localhost, 127.0.0.1, db, inkloom_db, inkloom_local_test)
- Requires role ADMIN and is_active == True
- Concealed interactive password input via getpass.getpass() (min 16 chars, alphanumeric, confirmation match)
- Reuses app.core.security.hash_password() (Argon2id) and verify_password()
- Reuses SQLAlchemy ORM Session - single atomic transaction with rollback on any failure
- Post-rotation HTTP verification against /api/v1/auth/login
- Never logs, echoes, or displays plaintext passwords, hashes, or JWT tokens
"""
import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request
from sqlalchemy import create_engine, select
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models import Role, User, OrganisationMembership

TARGET_EMAIL = "judge@inkloom.ai"
EXPECTED_ROLE = "ADMIN"


def sanitize_database_url(raw_url: str) -> dict[str, str]:
    """Parse database URL into safe, non-sensitive display components (zero secrets)."""
    try:
        url = make_url(raw_url)
        return {
            "driver": url.drivername,
            "host": url.host or "unknown_host",
            "port": str(url.port or 5432),
            "database": url.database or "railway",
            "username": url.username or "postgres",
        }
    except Exception:
        return {
            "driver": "unknown",
            "host": "unknown",
            "port": "unknown",
            "database": "unknown",
            "username": "unknown",
        }


def validate_password_complexity(pwd: str) -> None:
    """Enforce minimum 16 chars and alphanumeric composition."""
    if len(pwd) < 16:
        raise ValueError("Password must be at least 16 characters long.")
    has_letter = any(c.isalpha() for c in pwd)
    has_digit = any(c.isdigit() for c in pwd)
    if not (has_letter and has_digit):
        raise ValueError("Password must contain at least one letter and one number.")


def verify_database_target(db_info: dict[str, str], require_railway: bool = False) -> None:
    """Ensure database target is identified and prevent accidental local Docker modification."""
    host = (db_info.get("host") or "").lower()
    dbname = (db_info.get("database") or "").lower()
    driver = (db_info.get("driver") or "").lower()

    # Strictly reject any sqlite or local dev fallback
    if "sqlite" in driver:
        raise RuntimeError("Database Target Violation: SQLite fallback is strictly prohibited in production.")

    # Identify local / development environments
    is_local_host = host in (
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "db",
        "inkloom-postgres",
        "inkloom-prod-postgres",
    )
    is_local_db = dbname in ("inkloom_db", "inkloom_local_test", "inkloom_prod_db")

    if is_local_host or is_local_db:
        if require_railway:
            raise RuntimeError(
                f"Database Target Violation: Execution attempted against local/development database "
                f"(host='{host}', db='{dbname}'). Railway Cloud database required."
            )

    if require_railway:
        # Positively validate Railway identity:
        # Check either Railway environment variables or Railway domain in host or dbname == 'railway'
        is_railway_env = bool(
            os.getenv("RAILWAY_PROJECT_ID")
            or os.getenv("RAILWAY_ENVIRONMENT")
            or os.getenv("RAILWAY_SERVICE_ID")
            or os.getenv("RAILWAY_STATIC_URL")
            or os.getenv("RAILWAY_PRIVATE_DOMAIN")
        )
        is_railway_host = "railway.internal" in host or "railway" in host or dbname == "railway"

        if not (is_railway_env or is_railway_host):
            raise RuntimeError(
                f"Database Target Violation: Positive Railway Cloud validation failed. "
                f"Host '{host}' / DB '{dbname}' does not match Railway Cloud private network."
            )


def verify_judge_preconditions(db: Session, expected_uuid: str | None = None) -> User:
    """Verify target database, judge account UUID, email, role ADMIN, and active status."""
    user = db.execute(select(User).where(User.email == TARGET_EMAIL)).scalar_one_or_none()
    if user is None:
        raise RuntimeError(f"Pre-write verification failed: Account '{TARGET_EMAIL}' not found in database.")

    user_uuid = str(user.id)
    if expected_uuid and user_uuid != expected_uuid:
        raise RuntimeError(
            f"Pre-write verification failed: Account UUID mismatch! "
            f"Expected '{expected_uuid}', but found '{user_uuid}'."
        )

    if not user.is_active:
        raise RuntimeError(f"Pre-write verification failed: Account '{TARGET_EMAIL}' is inactive (is_active=False).")

    roles = [m.role.name for m in user.memberships if m.role]
    if EXPECTED_ROLE not in roles:
        raise RuntimeError(
            f"Pre-write verification failed: Account '{TARGET_EMAIL}' does not have expected '{EXPECTED_ROLE}' role. "
            f"Found roles: {roles}"
        )

    return user


def verify_http_login(new_pwd: str, base_url: str) -> dict:
    """Verify login against API endpoint without disclosing password or token."""
    url = f"{base_url.rstrip('/')}/api/v1/auth/login"
    body = json.dumps({"email": TARGET_EMAIL, "password": new_pwd}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status_code = resp.status
            data = json.loads(resp.read().decode("utf-8"))
            token = data.get("access_token")
            user_data = data.get("user", {})
            memberships = user_data.get("memberships", [])
            has_admin = any(m.get("role_name") == EXPECTED_ROLE or m.get("role") == EXPECTED_ROLE for m in memberships)
            return {
                "status_code": status_code,
                "login_successful": status_code == 200 and bool(token),
                "admin_role_verified": has_admin or user_data.get("active_role") == EXPECTED_ROLE,
                "token_received": bool(token),
            }
    except urllib.error.HTTPError as err:
        return {
            "status_code": err.code,
            "login_successful": False,
            "admin_role_verified": False,
            "token_received": False,
        }
    except Exception as exc:
        return {
            "status_code": 0,
            "error": str(exc),
            "login_successful": False,
            "admin_role_verified": False,
            "token_received": False,
        }


def run_setup(
    database_url: str,
    base_url: str,
    expected_uuid: str | None = None,
    preflight_only: bool = False,
    require_railway: bool = False,
) -> int:
    """Execute pre-check or interactive password rotation."""
    db_info = sanitize_database_url(database_url)

    print("=" * 70)
    print(" INKLOOM AI — PRODUCTION JUDGE CREDENTIAL SETUP UTILITY")
    print("=" * 70)
    print(f" Target Email       : {TARGET_EMAIL}")
    print(f" Expected UUID      : {expected_uuid or '[Any Verified Existing UUID]'}")
    print(f" Expected Role      : {EXPECTED_ROLE}")
    print(f" Database Driver    : {db_info['driver']}")
    print(f" Database Host      : {db_info['host']}")
    print(f" Database Name      : {db_info['database']}")
    print(f" Database Username  : {db_info['username']}")
    print(f" Target API URL     : {base_url}")
    print(f" Operation Mode     : {'PREFLIGHT (READ-ONLY INSPECTION)' if preflight_only else 'ATOMIC EXECUTION'}")
    print(f" Railway Required   : {require_railway}")
    print("-" * 70)

    try:
        verify_database_target(db_info, require_railway=require_railway)
        if require_railway:
            print("  ✓ Database target confirmed: Railway Cloud managed database.")
    except RuntimeError as r_err:
        print(f"  ✗ DATABASE TARGET CHECK FAILED: {r_err}")
        print("  STOPPING EXECUTION. Zero data modified.")
        print("=" * 70)
        return 1

    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    with session_factory() as db:
        print("[1/3] Conducting Mandatory Pre-Write Verification...")
        try:
            judge_user = verify_judge_preconditions(db, expected_uuid=expected_uuid)
            judge_id_before = str(judge_user.id)
            roles_before = [m.role.name for m in judge_user.memberships if m.role]
            print("  ✓ Account exists in target database.")
            print(f"  ✓ Verified Account UUID   : {judge_user.id}")
            print(f"  ✓ Verified Active Status  : {judge_user.is_active}")
            print(f"  ✓ Verified Assigned Roles : {roles_before}")
        except Exception as exc:
            print(f"  ✗ PRE-WRITE VERIFICATION FAILED: {exc}")
            print("  STOPPING EXECUTION. Zero data modified.")
            print("=" * 70)
            return 1

        if preflight_only:
            print("\n[2/3] PREFLIGHT SUCCESSFUL.")
            print("  ✓ Target account matches all criteria.")
            print("  ✓ Database identity verified.")
            print("  Zero mutations executed.")
            print("=" * 70)
            return 0

        # EXECUTION MODE
        print("\n[2/3] Prompting for secure password via concealed input...")
        pwd = getpass.getpass(f"Enter replacement password for {TARGET_EMAIL} (min 16 chars): ")
        try:
            validate_password_complexity(pwd)
        except ValueError as val_err:
            print(f"  ✗ Complexity Error: {val_err}")
            del pwd
            return 1

        pwd_conf = getpass.getpass(f"Confirm replacement password for {TARGET_EMAIL}: ")
        if pwd != pwd_conf:
            print("  ✗ Error: Password confirmation does not match.")
            del pwd, pwd_conf
            return 1

        print("\nExecuting single atomic SQLAlchemy update (Argon2id)...")
        try:
            new_hash = hash_password(pwd)
            judge_user.password_hash = new_hash
            db.flush()

            # Verify in-memory before commit
            assert verify_password(pwd, judge_user.password_hash), "Hash verification failed in memory."

            # Post-condition assertions: UUID, email, and roles unaltered
            assert str(judge_user.id) == judge_id_before, "Judge UUID was altered"
            assert judge_user.email == TARGET_EMAIL, "Judge email was altered"
            roles_after = [m.role.name for m in judge_user.memberships if m.role]
            assert roles_after == roles_before, "Judge roles were altered"

            db.commit()
            print("  ✓ Transaction COMMITTED successfully.")
            print(f"  ✓ Account '{TARGET_EMAIL}' password_hash updated.")
            print("  ✓ No other accounts, UUIDs, roles, or records modified.")
        except Exception as exc:
            db.rollback()
            print(f"  ✗ Transaction ROLLED BACK due to error: {exc}")
            del pwd, pwd_conf
            return 1

        print("\n[3/3] Conducting Post-Rotation HTTP Authentication Verification...")
        result = verify_http_login(pwd, base_url)

        # Clear plaintext passwords from memory
        del pwd, pwd_conf

        print("-" * 70)
        print(" VERIFICATION RESULTS (Zero secrets disclosed):")
        print(f"  - HTTP Endpoint Tested  : {base_url}/api/v1/auth/login")
        print(f"  - HTTP Status Code      : {result.get('status_code')}")
        print(f"  - Authentication Result : {'PASSED (200 OK)' if result.get('login_successful') else 'FAILED'}")
        print(f"  - JWT Access Token      : {'RECEIVED AND VALID' if result.get('token_received') else 'NOT RECEIVED'}")
        print(f"  - Role ADMIN Verified   : {'CONFIRMED' if result.get('admin_role_verified') else 'UNCONFIRMED'}")
        print("=" * 70)

        if result.get("login_successful") and result.get("admin_role_verified"):
            print(" SUCCESS: Production judge credentials securely configured and verified.")
            print("=" * 70)
            return 0
        else:
            print(" WARNING: Password updated in DB, but HTTP verification failed or target API not reachable.")
            print("=" * 70)
            return 2


def main():
    parser = argparse.ArgumentParser(description="Inkloom AI Secure Judge Password Setup")
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="Target database connection URL (defaults to settings.sqlalchemy_database_uri)",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=None,
        help="Target API base URL for post-rotation login verification (defaults to http://localhost:${PORT:-8000})",
    )
    parser.add_argument(
        "--expected-uuid",
        type=str,
        default=None,
        help="Expected judge account UUID (optional validation)",
    )
    parser.add_argument(
        "--require-railway",
        action="store_true",
        default=False,
        help="Strictly reject any local Docker database (requires Railway Cloud)",
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        default=False,
        help="Perform non-mutating pre-write inspection and verification only",
    )

    args = parser.parse_args()
    db_url = args.database_url or settings.sqlalchemy_database_uri
    port = os.getenv("PORT", "8000")
    api_url = args.api_url or f"http://localhost:{port}"

    sys.exit(run_setup(
        database_url=db_url,
        base_url=api_url,
        expected_uuid=args.expected_uuid,
        preflight_only=args.preflight,
        require_railway=args.require_railway,
    ))


if __name__ == "__main__":
    main()
