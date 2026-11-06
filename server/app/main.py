"""FastAPI application entry point.

Run locally with: `uvicorn app.main:app --reload --port 8787` (from `server/`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.adapters.observability import configure_logging, install_request_metrics
from app.api.errors import install_error_handlers
from app.api.request_id import install_request_id
from app.api.routes import (
    admissions,
    assessments,
    courses,
    events,
    health,
    packages,
    parents,
    plans,
    runs,
    sessions,
    tasks,
    twin,
)
from app.bootstrap import Services, build_services
from app.config import APP_VERSION, QueueProvider, Settings, get_settings
from app.domain.ports.metrics import Metrics, NullMetrics


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    services: Services | None = getattr(app.state, "services", None)
    if services is None:
        services = build_services(settings)
        app.state.services = services
    await services.content_sync.refresh()  # reviewed course packages
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
    if settings.log_format == "json":
        configure_logging(settings.log_level)
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

    def _metrics() -> Metrics:
        current: Services | None = getattr(app.state, "services", None)
        return current.metrics if current is not None else NullMetrics()

    install_request_metrics(app, _metrics)
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
    for module in (
        health, twin, courses, tasks, sessions, runs, assessments, events, plans, parents,
    ):  # fmt: skip
        app.include_router(module.router)
    app.include_router(admissions.router)
    app.include_router(packages.authoring)
    app.include_router(packages.review)
    return app


app = create_app()
