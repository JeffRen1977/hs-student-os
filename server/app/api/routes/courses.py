"""Course catalog, enrollment, and per-course agent entry points (Steps 10–11)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api import presenters
from app.api.dependencies.auth import Actor, ServicesDep
from app.api.dependencies.commands import IdempotencyKeyHeader, command_key
from app.api.responses import respond
from app.api.routes.params import CoursePath
from app.schemas import course as c

router = APIRouter(prefix="/api/courses", tags=["courses"])


@router.get("/catalog", response_model=c.CatalogResponse)
async def catalog(actor: Actor, services: ServicesDep) -> JSONResponse:
    entries = await services.courses.catalog(actor)
    return respond(c.CatalogResponse(courses=[presenters.catalog_entry(e) for e in entries]))


@router.get("/enrolled", response_model=c.EnrolledCoursesResponse)
async def enrolled(actor: Actor, services: ServicesDep) -> JSONResponse:
    courses = await services.courses.enrolled(actor)
    return respond(
        c.EnrolledCoursesResponse(enrollments=[presenters.enrolled_course(x) for x in courses])
    )


@router.post("/enroll", response_model=c.Enrollment)
async def enroll(
    body: c.EnrollRequest,
    request: Request,
    actor: Actor,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.courses.enroll(actor, body.course_id, cmd)
    return respond(presenters.enrollment(outcome.value), replayed=outcome.replayed)


@router.post("/unenroll", response_model=c.Enrollment)
async def unenroll(
    body: c.UnenrollRequest,
    request: Request,
    actor: Actor,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.courses.unenroll(actor, body.course_id, cmd)
    return respond(presenters.enrollment(outcome.value), replayed=outcome.replayed)


@router.get("/{course_id}", response_model=c.CatalogEntry)
async def course(course_id: CoursePath, actor: Actor, services: ServicesDep) -> JSONResponse:
    return respond(presenters.catalog_entry(await services.courses.course(actor, course_id)))


@router.get("/{course_id}/agent", response_model=c.CourseAgentView)
async def course_agent(course_id: CoursePath, actor: Actor, services: ServicesDep) -> JSONResponse:
    return respond(
        presenters.course_agent(await services.courses.agent(actor, course_id), services.packs)
    )
