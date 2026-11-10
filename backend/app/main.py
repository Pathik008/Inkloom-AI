"""Inkloom AI — FastAPI Application Entrypoint."""
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from app.api.routes import api_router
from app.api.routes.health import build_health_payload
from app.core.config import settings
from app.database import get_db, init_db
from app.schemas import HealthResponse

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan managing startup and shutdown tasks.

    - Schema management is handled exclusively by Alembic migrations (create_all removed).
    - Decoupled from global engine: honors test dependency overrides for get_db.
    - Seeds roles and permissions through explicit init_db() mechanism.
    - Never silently ignores production database connection failures.
    """
    if get_db in application.dependency_overrides:
        override_fn = application.dependency_overrides[get_db]
        try:
            res = override_fn()
            if hasattr(res, "__next__") or hasattr(res, "__iter__"):
                gen = iter(res)
                try:
                    session = next(gen)
                    init_db(session=session)
                finally:
                    if hasattr(gen, "close"):
                        gen.close()
            elif isinstance(res, Session):
                init_db(session=res)
        except Exception as exc:
            logger.debug("Dependency override role initialization in lifespan: %s", exc)
    else:
        is_production = settings.APP_ENV.lower() in ("production", "staging")
        init_db(fail_fast=is_production)

    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Inkloom AI — AI-Powered Brand Compliance and Marketing Content Review Platform. "
            "Provides deterministic rule enforcement, RAG-grounded semantic analysis, "
            "and SHA-256 bound human approval workflows."
        ),
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.get(
        "/health",
        response_model=HealthResponse,
        responses={
            200: {"model": HealthResponse, "description": "System operational and database connected"},
            503: {"model": HealthResponse, "description": "Database disconnected or unavailable"},
        },
        tags=["System"],
    )
    async def root_health(response: Response) -> HealthResponse:
        """Top-level health check endpoint."""
        payload, http_code = build_health_payload()
        response.status_code = http_code
        return payload

    application.include_router(api_router, prefix=settings.API_V1_STR)
    return application


app = create_app()

if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
