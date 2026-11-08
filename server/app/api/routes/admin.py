"""Admins publish reviewer-approved courses for all students; no individual grants."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.dependencies.auth import Platform, ServicesDep
from app.api.dependencies.commands import IdempotencyKeyHeader, command_key
from app.api.responses import respond
from app.api.routes.packages import VersionPath, version_view
from app.api.routes.params import CoursePath
from app.schemas import package as pk

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/packages", response_model=pk.PackageVersionList)
async def publication_queue(actor: Platform, services: ServicesDep) -> JSONResponse:
    versions = await services.packages.publication_queue(actor)
    return respond(pk.PackageVersionList(versions=[version_view(v) for v in versions]))


@router.post(
    "/packages/{course_id}/versions/{version}/activate", response_model=pk.PackageVersionView
)
async def publish_course(
    course_id: CoursePath,
    version: VersionPath,
    body: pk.EmptyCommand,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.packages.activate(actor, course_id, version, cmd)
    return respond(version_view(outcome.value), replayed=outcome.replayed)


@router.post("/courses/{course_id}/retire", response_model=pk.PackageVersionView)
async def retire_course(
    course_id: CoursePath,
    body: pk.RetireRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.packages.retire(actor, course_id, body.notes, cmd)
    return respond(version_view(outcome.value), replayed=outcome.replayed)
