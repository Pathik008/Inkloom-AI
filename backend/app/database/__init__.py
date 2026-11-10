"""Database session, engine configuration, and Base declarative model.

PostgreSQL 16 + pgvector is the required primary database for Inkloom AI.
Silent fallback to SQLite is strictly forbidden. SQLite is only permitted if
explicitly enabled via ALLOW_SQLITE_DEV_FALLBACK=true or an explicit sqlite:// URL.
"""
import socket
from collections.abc import Generator
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from app.core.config import settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


def _is_postgres_port_open() -> bool:
    host = settings.POSTGRES_HOST
    port = settings.POSTGRES_PORT
    if settings.DATABASE_URL:
        try:
            from sqlalchemy.engine.url import make_url
            parsed = make_url(settings.sqlalchemy_database_uri)
            if parsed.host:
                host = parsed.host
            if parsed.port:
                port = parsed.port
        except Exception:
            pass
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _resolve_active_database_uri() -> tuple[str, bool]:
    """Return (active_uri, is_using_sqlite).

    Zero silent fallback: If configured for PostgreSQL, it will strictly connect to
    PostgreSQL or fail clearly. SQLite fallback is only permitted if ALLOW_SQLITE_DEV_FALLBACK
    is explicitly set to True in development environments.
    """
    configured_uri = settings.sqlalchemy_database_uri

    # Explicit SQLite configuration
    if configured_uri.startswith("sqlite"):
        return configured_uri, True

    # PostgreSQL configuration
    if configured_uri.startswith("postgresql"):
        if not _is_postgres_port_open():
            if settings.APP_ENV == "development" and settings.ALLOW_SQLITE_DEV_FALLBACK:
                return settings.SQLITE_FALLBACK_URL, True
            # No silent fallback: retain PostgreSQL URI so connection errors surface clearly
            return configured_uri, False
        return configured_uri, False

    return configured_uri, False


ACTIVE_DATABASE_URI, USING_SQLITE_FALLBACK = _resolve_active_database_uri()

engine = create_engine(
    ACTIVE_DATABASE_URI,
    pool_pre_ping=True,
    future=True,
    connect_args=(
        {"check_same_thread": False}
        if ACTIVE_DATABASE_URI.startswith("sqlite")
        else ({"connect_timeout": 3} if ACTIVE_DATABASE_URI.startswith("postgresql") else {})
    ),
)

# Enforce foreign key constraints when running on SQLite
if ACTIVE_DATABASE_URI.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency that yields a SQLAlchemy database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_connection() -> tuple[bool, str]:
    """Probe the active database to report real connectivity and engine status."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        if ACTIVE_DATABASE_URI.startswith("postgresql"):
            return True, "connected (PostgreSQL 16 + pgvector)"
        if USING_SQLITE_FALLBACK:
            return True, "connected (SQLite dev fallback: ALLOW_SQLITE_DEV_FALLBACK=true)"
        return True, f"connected ({ACTIVE_DATABASE_URI.split(':')[0]})"
    except Exception as exc:
        if ACTIVE_DATABASE_URI.startswith("postgresql"):
            return False, f"PostgreSQL connection error ({exc.__class__.__name__})"
        if USING_SQLITE_FALLBACK:
            return False, f"SQLite fallback error ({exc.__class__.__name__})"
        return False, f"unreachable ({exc.__class__.__name__})"


def init_db(
    session: Session | None = None,
    *,
    fail_fast: bool = False,
) -> bool:
    """Explicit, testable database initialization and RBAC seeding mechanism.

    - If an existing session is provided (e.g. from an injected test database or
      dependency override), seeds roles and permissions directly on it.
    - If no session is provided, attempts to seed using SessionLocal().
    - In production (or when fail_fast=True), connection failures raise RuntimeError.
    - In development/offline, connection failures are safely logged and return False.
    """
    from app.services.rbac_service import seed_roles_and_permissions

    # Case 1: Session provided explicitly (e.g. injected SQLite test database)
    if session is not None:
        seed_roles_and_permissions(session)
        return True

    # Case 2: Production / Fail-fast enforcement
    is_prod = settings.APP_ENV.lower() in ("production", "staging") or fail_fast
    if is_prod:
        # Enforce strict production connectivity check (never silently ignore)
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:
            raise RuntimeError(
                f"Database connection failed during production startup: {exc}"
            ) from exc

        db = SessionLocal()
        try:
            seed_roles_and_permissions(db)
            return True
        except Exception as exc:
            raise RuntimeError(
                f"Database initialization failed during production startup: {exc}"
            ) from exc
        finally:
            db.close()

    # Case 3: Development / Offline environment
    db_ok, _ = check_database_connection()
    if not db_ok:
        return False

    try:
        db = SessionLocal()
        try:
            seed_roles_and_permissions(db)
            return True
        finally:
            db.close()
    except Exception:
        return False
