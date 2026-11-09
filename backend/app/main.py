"""Inkloom AI — FastAPI Application Entrypoint."""
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import api_router
from app.api.routes.health import build_health_payload
from app.core.config import settings
from app.database import Base, SessionLocal, engine
from app.schemas import HealthResponse
from app.services.rbac_service import seed_roles_and_permissions


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Ensure database tables and predefined RBAC roles/permissions exist on startup."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_roles_and_permissions(db)
    finally:
        db.close()
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

    @application.get("/health", response_model=HealthResponse, tags=["System"])
    async def root_health() -> HealthResponse:
        """Top-level health check endpoint."""
        return build_health_payload()

    application.include_router(api_router, prefix=settings.API_V1_STR)
    return application


app = create_app()

if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
