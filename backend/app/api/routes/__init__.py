"""API route modules."""
from fastapi import APIRouter
from app.api.routes import auth, brand_kits, brand_rules, compliance, health, invitations, organisations

api_router = APIRouter()
api_router.include_router(health.router, tags=["System"])
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(organisations.router, prefix="/organisations", tags=["Organisations & RBAC"])
api_router.include_router(
    brand_kits.router,
    prefix="/organisations/{organisation_id}/brand-kits",
    tags=["Brand Hub"],
)
api_router.include_router(
    brand_rules.router,
    prefix="/organisations/{organisation_id}/brand-kits/{brand_kit_id}/versions/{version_id}/rules",
    tags=["Brand Hub Rules"],
)
api_router.include_router(
    compliance.router,
    prefix="/organisations/{organisation_id}/compliance/submissions",
    tags=["Compliance"],
)
api_router.include_router(
    compliance.reviewers_router,
    prefix="/organisations/{organisation_id}/compliance/reviewers",
    tags=["Compliance"],
)
api_router.include_router(
    compliance.metrics_router,
    prefix="/organisations/{organisation_id}/compliance/metrics",
    tags=["Compliance"],
)
api_router.include_router(invitations.router, prefix="/invitations", tags=["Invitations"])
