"""FastAPI application entry point.

Run locally with: `uvicorn app.main:app --reload --port 8787` (from `server/`).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_error_handlers
from app.api.request_id import install_request_id
from app.api.routes import health
from app.config import APP_VERSION, Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    # Settings validation runs here, so an unsafe deployed config aborts startup.
    settings = settings or get_settings()
    app = FastAPI(
        title="High School Student OS API",
        version=APP_VERSION,
        docs_url=None if settings.is_deployed else "/api/docs",
        openapi_url=None if settings.is_deployed else "/api/openapi.json",
        redoc_url=None,
    )
    app.state.settings = settings
    install_request_id(app)
    install_error_handlers(app)
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_methods=["GET", "POST", "PATCH"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "If-Match"],
            expose_headers=["ETag", "X-Request-Id", "Idempotency-Replayed"],
        )
    app.include_router(health.router)
    return app


app = create_app()
