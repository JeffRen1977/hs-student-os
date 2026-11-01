"""FastAPI application entry point.

Run locally with: `uvicorn app.main:app --reload --port 8787` (from `server/`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import install_error_handlers
from app.api.request_id import install_request_id
from app.api.routes import assessments, courses, events, health, runs, sessions, tasks, twin
from app.bootstrap import Services, build_services
from app.config import APP_VERSION, QueueProvider, Settings, get_settings


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    services: Services | None = getattr(app.state, "services", None)
    if services is None:
        services = build_services(settings)
        app.state.services = services
    loop = services.local_worker
    run_loop = (
        loop is not None
        and settings.queue_provider is QueueProvider.LOCAL
        and settings.local_worker_enabled
        and not settings.is_deployed
    )
    if run_loop and loop is not None:
        loop.start()
    try:
        yield
    finally:
        if run_loop and loop is not None:
            await loop.stop()


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    # Settings validation runs here, so an unsafe deployed config aborts startup.
    settings = settings or get_settings()
    app = FastAPI(
        title="High School Student OS API",
        version=APP_VERSION,
        docs_url=None if settings.is_deployed else "/api/docs",
        openapi_url=None if settings.is_deployed else "/api/openapi.json",
        redoc_url=None,
        lifespan=_lifespan,
    )
    app.state.settings = settings
    if services is not None:
        app.state.services = services
    install_request_id(app)
    install_error_handlers(app)
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_methods=["GET", "POST", "PATCH"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Idempotency-Key",
                "If-Match",
                "Last-Event-ID",
            ],
            expose_headers=["ETag", "X-Request-Id", "Idempotency-Replayed"],
        )
    for module in (health, twin, courses, tasks, sessions, runs, assessments, events):
        app.include_router(module.router)
    return app


app = create_app()
