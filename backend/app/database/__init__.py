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
    try:
        with socket.create_connection((settings.POSTGRES_HOST, settings.POSTGRES_PORT), timeout=0.4):
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
    if ACTIVE_DATABASE_URI.startswith("postgresql"):
        if not _is_postgres_port_open():
            return False, f"PostgreSQL unreachable: port {settings.POSTGRES_PORT} closed on {settings.POSTGRES_HOST}"
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True, "connected (PostgreSQL 16 + pgvector)"
        except Exception as exc:
            return False, f"PostgreSQL connection error ({exc.__class__.__name__})"

    if USING_SQLITE_FALLBACK:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True, "connected (SQLite dev fallback: ALLOW_SQLITE_DEV_FALLBACK=true; PostgreSQL port 5432 offline)"
        except Exception as exc:
            return False, f"SQLite fallback error ({exc.__class__.__name__})"

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True, f"connected ({ACTIVE_DATABASE_URI.split(':')[0]})"
    except Exception as exc:
        return False, f"unreachable ({exc.__class__.__name__})"
