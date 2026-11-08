"""API route modules."""
from fastapi import APIRouter
from app.api.routes import auth, health, invitations, organisations

api_router = APIRouter()
api_router.include_router(health.router, tags=["System"])
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(organisations.router, prefix="/organisations", tags=["Organisations & RBAC"])
api_router.include_router(invitations.router, prefix="/invitations", tags=["Invitations"])
