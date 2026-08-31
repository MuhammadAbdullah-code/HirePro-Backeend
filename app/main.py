from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import settings
from app.db import close_database, create_indexes, get_database, migrate_database
from app.seed import seed_reference_data


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Manage resources that live for the duration of the application."""
    database = get_database()
    migrate_database(database)
    create_indexes(database)
    seed_reference_data(database)
    yield
    close_database()


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @application.middleware("http")
    async def enforce_maintenance_mode(request, call_next):
        exempt = (
            request.method == "OPTIONS"
            or request.url.path.startswith(f"{settings.api_prefix}/admin")
            or request.url.path in {f"{settings.api_prefix}/health", "/docs", "/openapi.json", "/redoc"}
            or request.url.path.startswith("/uploads/")
        )
        if not exempt:
            try:
                item = get_database().platform_settings.find_one({"_id": "platform"}, {"settings.health": 1}) or {}
                health = item.get("settings", {}).get("health", {})
                now = datetime.now(UTC)
                start = health.get("scheduled_start")
                end = health.get("scheduled_end")
                if isinstance(start, datetime) and start.tzinfo is None:
                    start = start.replace(tzinfo=UTC)
                if isinstance(end, datetime) and end.tzinfo is None:
                    end = end.replace(tzinfo=UTC)
                scheduled = (start is None or now >= start) and (end is None or now <= end)
                allowed_ips = {
                    value.strip() for value in str(health.get("allowed_ips", "")).split(",") if value.strip()
                }
                client_ip = request.client.host if request.client else ""
                if health.get("maintenance_mode") and scheduled and client_ip not in allowed_ips:
                    return JSONResponse(
                        status_code=503,
                        content={
                            "detail": "Service is temporarily unavailable for maintenance",
                            "title": health.get("maintenance_title", "We’ll be back shortly"),
                            "message": health.get("maintenance_message", "Scheduled maintenance is in progress."),
                            "expected_restoration": health.get("expected_restoration", ""),
                            "status_page_url": health.get("status_page_url", ""),
                        },
                        headers={"Retry-After": "300"},
                    )
            except Exception:
                pass
        return await call_next(request)
    application.include_router(api_router, prefix=settings.api_prefix)
    application.mount("/uploads", StaticFiles(directory=settings.upload_directory, check_dir=False), name="uploads")
    return application


app = create_app()
