"""Backend test suite for Inkloom AI Phase 1 Foundation."""
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_root_health_endpoint() -> None:
    """Verify /health returns 200 and a valid schema payload."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["service"] == "Inkloom AI"
    assert payload["version"] == "0.1.0"
    assert payload["pgvector_target_dimension"] == 1024
    assert isinstance(payload["database_connected"], bool)
    assert "database_status" in payload
    assert "timestamp" in payload


@pytest.mark.anyio
async def test_api_v1_health_endpoint() -> None:
    """Verify /api/v1/health returns 200 and matches the root health payload structure."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["service"] == "Inkloom AI"
    assert payload["pgvector_target_dimension"] == 1024


@pytest.mark.anyio
async def test_cors_preflight_headers() -> None:
    """Verify CORS headers are returned for allowed local frontend origins."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_database_url_normalization_psycopg3() -> None:
    """Verify standard Railway/Heroku postgres:// and postgresql:// schemes normalize to postgresql+psycopg://."""
    from app.core.config import Settings

    # 1. postgres:// scheme normalized to postgresql+psycopg://
    s1 = Settings(SECRET_KEY="x" * 64, DATABASE_URL="postgres://user:pass@host:5432/db")
    assert s1.sqlalchemy_database_uri == "postgresql+psycopg://user:pass@host:5432/db"

    # 2. postgresql:// scheme without driver normalized to postgresql+psycopg://
    s2 = Settings(SECRET_KEY="x" * 64, DATABASE_URL="postgresql://user:pass@host:5432/db")
    assert s2.sqlalchemy_database_uri == "postgresql+psycopg://user:pass@host:5432/db"

    # 3. postgresql+psycopg:// scheme preserved as-is
    s3 = Settings(SECRET_KEY="x" * 64, DATABASE_URL="postgresql+psycopg://user:pass@host:5432/db")
    assert s3.sqlalchemy_database_uri == "postgresql+psycopg://user:pass@host:5432/db"

    # 4. Explicit non-default driver scheme preserved
    s4 = Settings(SECRET_KEY="x" * 64, DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/db")
    assert s4.sqlalchemy_database_uri == "postgresql+asyncpg://user:pass@host:5432/db"

    # 5. Default components synthesized with +psycopg driver when DATABASE_URL is empty
    s5 = Settings(
        SECRET_KEY="x" * 64,
        DATABASE_URL="",
        POSTGRES_USER="ink_user",
        POSTGRES_PASSWORD="secure_pass_123",
        POSTGRES_HOST="db_host",
        POSTGRES_PORT=5432,
        POSTGRES_DB="ink_db",
    )
    assert s5.sqlalchemy_database_uri == "postgresql+psycopg://ink_user:secure_pass_123@db_host:5432/ink_db"


@pytest.mark.anyio
async def test_health_endpoint_healthy_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify /health returns 200 and healthy status when database is operational."""
    from app.api.routes import health as health_route

    monkeypatch.setattr(
        health_route,
        "check_database_connection",
        lambda: (True, "connected (PostgreSQL 16 + pgvector)"),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["database_connected"] is True
    assert payload["database_status"] == "connected (PostgreSQL 16 + pgvector)"


@pytest.mark.anyio
async def test_health_endpoint_unhealthy_state_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify /health returns 503 and unhealthy status when database is disconnected."""
    from app.api.routes import health as health_route

    monkeypatch.setattr(
        health_route,
        "check_database_connection",
        lambda: (False, "PostgreSQL connection error (OperationalError)"),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unhealthy"
    assert payload["database_connected"] is False
    assert "OperationalError" in payload["database_status"]


@pytest.mark.anyio
async def test_api_v1_health_unhealthy_state_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify /api/v1/health returns 503 and unhealthy status when database is disconnected."""
    from app.api.routes import health as health_route

    monkeypatch.setattr(
        health_route,
        "check_database_connection",
        lambda: (False, "PostgreSQL unreachable: port 5432 closed"),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/health")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unhealthy"
    assert payload["database_connected"] is False
