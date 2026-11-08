"""Pytest configuration and environment fixtures for Inkloom AI."""
import os
import secrets
from collections.abc import Generator
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure tests have a strong, non-default SECRET_KEY configured before any app modules import Settings
TEST_JWT_SECRET = secrets.token_hex(32)
os.environ.setdefault("SECRET_KEY", TEST_JWT_SECRET)
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ALLOW_SQLITE_DEV_FALLBACK", "true")

from app.core.rate_limit import get_rate_limiter
from app.core.security import auth_rate_limiter
from app.database import Base, get_db
from app.main import app
from app.services.rbac_service import seed_roles_and_permissions


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide an isolated in-memory SQLAlchemy database session for each test."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(test_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSessionLocal()
    seed_roles_and_permissions(session)
    auth_rate_limiter.reset()
    get_rate_limiter().reset()

    def _override_get_db() -> Generator[Session, None, None]:
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield session
    finally:
        app.dependency_overrides.clear()
        session.close()
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()
