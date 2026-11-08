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
