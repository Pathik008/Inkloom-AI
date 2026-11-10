"""Health and readiness endpoints."""
from datetime import datetime, timezone
from fastapi import APIRouter, Response, status
from app.core.config import settings
from app.database import check_database_connection
from app.schemas import HealthResponse

router = APIRouter()


def build_health_payload() -> tuple[HealthResponse, int]:
    db_ok, db_msg = check_database_connection()
    payload = HealthResponse(
        status="healthy" if db_ok else "unhealthy",
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
        database_status=db_msg,
        database_connected=db_ok,
        pgvector_target_dimension=settings.EMBEDDING_DIMENSION,
        timestamp=datetime.now(timezone.utc),
    )
    http_code = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return payload, http_code


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={
        200: {"model": HealthResponse, "description": "System operational and database connected"},
        503: {"model": HealthResponse, "description": "Database disconnected or unavailable"},
    },
    summary="Check API and database health",
)
async def get_health(response: Response) -> HealthResponse:
    """Return real-time operational status of Inkloom AI backend and database."""
    payload, http_code = build_health_payload()
    response.status_code = http_code
    return payload
