"""Health and readiness endpoints."""
from datetime import datetime, timezone
from fastapi import APIRouter
from app.core.config import settings
from app.database import check_database_connection
from app.schemas import HealthResponse

router = APIRouter()


def build_health_payload() -> HealthResponse:
    db_ok, db_msg = check_database_connection()
    return HealthResponse(
        status="healthy",
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.APP_ENV,
        database_status=db_msg,
        database_connected=db_ok,
        pgvector_target_dimension=settings.EMBEDDING_DIMENSION,
        timestamp=datetime.now(timezone.utc),
    )


@router.get("/health", response_model=HealthResponse, summary="Check API and database health")
async def get_health() -> HealthResponse:
    """Return real-time operational status of Inkloom AI backend and database."""
    return build_health_payload()
