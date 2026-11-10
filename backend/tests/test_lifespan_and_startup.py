"""Regression test suite for FastAPI lifespan, startup decoupling, and database initialization."""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.database import Base, get_db, init_db
from app.main import app
from app.models import Permission, Role, RoleName


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_lifespan_startup_without_postgres_returns_health() -> None:
    """Verify application starts cleanly and serves /health when PostgreSQL is offline."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert isinstance(payload["database_connected"], bool)


@pytest.mark.anyio
async def test_lifespan_with_dependency_override_sqlite() -> None:
    """Verify lifespan seamlessly honors injected test database and seeds roles."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=test_engine)

    def _override_get_db():
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/api/v1/auth/register",
                json={
                    "full_name": "Lifespan Test User",
                    "email": "lifespan.test@example.com",
                    "password": "SecurePassword123!",
                    "confirm_password": "SecurePassword123!",
                    "organisation_name": "Lifespan Org",
                },
            )
            assert resp.status_code == 201
            data = resp.json()
            assert "access_token" in data
            assert data["user"]["email"] == "lifespan.test@example.com"
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


def test_init_db_explicit_mechanism_and_role_seeding() -> None:
    """Verify init_db explicitly and idempotently seeds roles and permissions on any session."""
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=test_engine)
    try:
        with Session(test_engine) as session:
            # First pass: seed
            ok = init_db(session=session)
            assert ok is True
            roles = session.execute(select(Role)).scalars().all()
            perms = session.execute(select(Permission)).scalars().all()
            assert len(roles) == 4
            assert len(perms) == 10
            assert set(r.name for r in roles) == set(RoleName.ALL)

            # Second pass: idempotent
            ok_again = init_db(session=session)
            assert ok_again is True
            roles_again = session.execute(select(Role)).scalars().all()
            assert len(roles_again) == 4
    finally:
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


def test_production_fail_fast_on_database_failure() -> None:
    """Verify init_db with fail_fast=True raises RuntimeError if connection or init fails."""
    with pytest.raises(RuntimeError, match="during production startup"):
        init_db(fail_fast=True)


@pytest.mark.anyio
async def test_lifespan_generator_closure_on_success_and_failure() -> None:
    """SEC-10: Verify lifespan closes dependency override generators on both success and failure."""
    from app.main import lifespan

    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=test_engine)

    # Scenario 1: Successful generator consumption and immediate closure
    success_gen_closed = False

    def _success_gen():
        nonlocal success_gen_closed
        with Session(test_engine) as session:
            try:
                yield session
            finally:
                success_gen_closed = True

    app.dependency_overrides[get_db] = _success_gen
    try:
        async with lifespan(app):
            assert success_gen_closed is True, "Generator must be closed via gen.close() during lifespan startup"
    finally:
        app.dependency_overrides.clear()

    # Scenario 2: Generator closure even when init_db fails on invalid session
    failure_gen_closed = False

    def _failure_gen():
        nonlocal failure_gen_closed
        try:
            yield "invalid-session-object"
        finally:
            failure_gen_closed = True

    app.dependency_overrides[get_db] = _failure_gen
    try:
        async with lifespan(app):
            assert failure_gen_closed is True, "Generator must be closed via gen.close() even when session processing fails"
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()

