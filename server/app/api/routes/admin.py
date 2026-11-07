"""Course access administration for platform admins (Step 42, API.md §6.5.6).

Platform admins are platform members (`platformMembers/{uid}`, role `admin`); the service
checks `entitlements:manage`, so authors and reviewers get 403, and students and parents,
who are not platform members, get 403 from the dependency. Every POST needs an
Idempotency-Key.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.dependencies.auth import Platform, ServicesDep
from app.api.dependencies.commands import IdempotencyKeyHeader, command_key
from app.api.responses import respond
from app.api.routes.params import IdPath
from app.domain.access_service import AccessChangeResult, BulkResult, StudentAccess
from app.domain.types.access import AccessChange
from app.schemas import admin as sc

router = APIRouter(prefix="/api/admin", tags=["admin"])


def access_view(a: StudentAccess) -> sc.StudentAccessView:
    e = a.access.entitlements
    return sc.StudentAccessView(
        student_id=a.student_id,
        display_name=a.display_name,
        access=sc.AccessRecordView(
            ap_courses=list(e.ap_courses),
            courses=list(e.courses),
            admissions=e.admissions,
            updated_at=a.access.updated_at,
            updated_by=a.access.updated_by,
        ),
        courses=[
            sc.CourseAccessView(
                course_id=c.course.course_id,
                name=c.course.name,
                category=c.course.category,
                availability=c.course.availability,
                granted=c.granted,
                enrollment=None
                if c.enrollment is None
                else sc.EnrollmentView(
                    status=c.enrollment.status,
                    enrolled_at=c.enrollment.enrolled_at,
                    unenrolled_at=c.enrollment.unenrolled_at,
                ),
            )
            for c in a.courses
        ],
        audit=[
            sc.AuditEntryView(
                audit_id=x.audit_id,
                course_id=x.course_id,
                change=x.change.value,
                reason=x.reason,
                actor_id=x.actor_id,
                at=x.at,
            )
            for x in a.audit
        ],
    )


def change_view(r: AccessChangeResult) -> sc.AccessChangeView:
    return sc.AccessChangeView(changed=r.changed, audit_id=r.audit_id, access=access_view(r.access))


def bulk_view(results: list[BulkResult]) -> sc.BulkAccessView:
    count = {s: sum(r.status == s for r in results) for s in ("changed", "unchanged", "failed")}
    return sc.BulkAccessView(
        results=[
            sc.BulkResultView(
                student_id=r.student_id,
                status=r.status,  # type: ignore[arg-type]
                audit_id=r.audit_id,
                error_code=r.error_code,
                message=r.message,
            )
            for r in results
        ],
        **count,
    )


@router.get("/students/{student_id}/access", response_model=sc.StudentAccessView)
async def get_student_access(
    student_id: IdPath, actor: Platform, services: ServicesDep
) -> JSONResponse:
    await services.content_sync.ensure_fresh()  # authored courses in the catalog
    return respond(access_view(await services.access.view(actor, student_id)))


async def _change(
    change: AccessChange,
    student_id: str,
    body: sc.AccessChangeRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: str | None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    await services.content_sync.ensure_fresh()
    outcome = await services.access.change(
        actor, student_id, body.course_id, change, body.reason, cmd
    )
    return respond(change_view(outcome.value), replayed=outcome.replayed)


@router.post("/students/{student_id}/access/grant", response_model=sc.AccessChangeView)
async def grant_access(
    student_id: IdPath,
    body: sc.AccessChangeRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    return await _change(
        AccessChange.GRANT, student_id, body, request, actor, services, idempotency_key
    )


@router.post("/students/{student_id}/access/revoke", response_model=sc.AccessChangeView)
async def revoke_access(
    student_id: IdPath,
    body: sc.AccessChangeRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    return await _change(
        AccessChange.REVOKE, student_id, body, request, actor, services, idempotency_key
    )


@router.post("/access/bulk", response_model=sc.BulkAccessView)
async def bulk_access(
    body: sc.BulkAccessRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    await services.content_sync.ensure_fresh()
    results = await services.access.bulk(
        actor, body.student_ids, body.course_id, AccessChange(body.change), body.reason, cmd
    )
    return respond(bulk_view(results))
