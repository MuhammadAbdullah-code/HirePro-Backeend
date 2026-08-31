from fastapi import APIRouter

from app.api.routes.admin import router as admin_router
from app.api.routes.admin_settings import router as admin_settings_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.auth import router as auth_router
from app.api.routes.catalog import router as catalog_router
from app.api.routes.dashboards import router as dashboards_router
from app.api.routes.health import router as health_router
from app.api.routes.homepage import router as homepage_router
from app.api.routes.provider import router as provider_router
from app.api.routes.support import router as support_router
from app.api.routes.user_features import router as user_features_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(homepage_router)
api_router.include_router(auth_router, tags=["authentication"])
api_router.include_router(catalog_router)
api_router.include_router(dashboards_router)
api_router.include_router(provider_router)
api_router.include_router(support_router)
api_router.include_router(user_features_router)
api_router.include_router(analytics_router, tags=["analytics"])
api_router.include_router(admin_settings_router)
api_router.include_router(admin_router, tags=["admin"])
