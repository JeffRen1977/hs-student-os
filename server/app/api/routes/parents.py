"""Parent links and scoped summaries (Step 36, API.md §6.4).

Student side (`/api/parent-links`): create an invite (scopes), list, revoke.
Parent side (`/api/parent/*`): redeem an invite, list linked students, read a summary.
A parent account is a separate identity; students get 403 on parent routes and parents
get 403 on student routes. Unknown, foreign, revoked or expired links are 404.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse

from app.api.dependencies.auth import Actor, ParentDep, ServicesDep
from app.api.dependencies.commands import IdempotencyKeyHeader, command_key
from app.api.responses import respond
from app.domain.types.actor import Permission
from app.domain.types.parent import ParentLink, ParentSummary
from app.schemas import parent as p
from app.schemas.common import EmptyCommand

router = APIRouter(prefix="/api", tags=["parents"])
LinkPath = Annotated[str, Path(pattern=r"^[A-Za-z0-9_\-]{1,64}$")]
StudentPath = Annotated[str, Path(pattern=r"^[A-Za-z0-9_\-]{1,64}$")]


def link_view(x: ParentLink) -> p.ParentLinkView:
    return p.ParentLinkView(
        link_id=x.link_id,
        status=x.status.value,
        scopes=list(x.scopes),  # type: ignore[arg-type]
        created_at=x.created_at,
        invite_expires_at=x.invite_expires_at,
        parent_display_name=x.parent_display_name,
        accepted_at=x.accepted_at,
        revoked_at=x.revoked_at,
    )


def summary_view(x: ParentSummary) -> p.ParentSummaryView:
    return p.ParentSummaryView(
        student_id=x.student_id,
        display_name=x.display_name,
        grade=x.grade,
        courses=[
            p.CourseProgressView(
                course_id=c.course_id,
                name=c.name,
                skills=[
                    p.SkillProgressView(
                        skill_id=s.skill_id,
                        level=s.level.value,
                        independent_evidence_count=s.independent_evidence_count,
                    )
                    for s in c.skills
                ],
                prediction="unavailable",
            )
            for c in x.courses
        ],
        week=p.WeekView(
            start=x.week.start.isoformat(),
            end=x.week.end.isoformat(),
            planned=x.week.planned,
            completed=x.week.completed,
            skipped=x.week.skipped,
            upcoming=[
                p.UpcomingTaskView(
                    course_id=t.course_id,
                    title=t.title,
                    scheduled_date=t.scheduled_date.isoformat(),
                    duration_min=t.duration_min,
                )
                for t in x.week.upcoming
            ],
        ),
        generated_at=x.generated_at,
    )


# ---- Student ----------------------------------------------------------------------------


@router.post("/parent-links", response_model=p.CreatedParentLink, status_code=201)
async def create_parent_link(
    body: p.CreateParentLinkRequest,
    request: Request,
    actor: Actor,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    out = await services.parents.invite(actor, frozenset(Permission(s) for s in body.scopes), cmd)
    view = p.CreatedParentLink(
        **link_view(out.value.link).model_dump(), invite_code=out.value.code or None
    )
    return respond(view, status=201, replayed=out.replayed)


@router.get("/parent-links", response_model=p.ParentLinkList)
async def list_parent_links(actor: Actor, services: ServicesDep) -> JSONResponse:
    links = await services.parents.list_links(actor)
    return respond(p.ParentLinkList(links=[link_view(x) for x in links]))


@router.post("/parent-links/{link_id}/revoke", response_model=p.ParentLinkView)
async def revoke_parent_link(
    link_id: LinkPath,
    body: EmptyCommand,
    request: Request,
    actor: Actor,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    out = await services.parents.revoke(actor, link_id, cmd)
    return respond(link_view(out.value), replayed=out.replayed)


# ---- Parent -----------------------------------------------------------------------------


@router.post("/parent/links/accept", response_model=p.LinkedStudent)
async def accept_parent_link(
    body: p.AcceptParentLinkRequest,
    request: Request,
    parent: ParentDep,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    actor, name = parent
    out = await services.parents.accept(actor, name, body.invite_code, cmd)
    students = {c.student_id: n for c, n in await services.parents.list_students(actor)}
    view = p.LinkedStudent(
        student_id=out.value.student_id,
        display_name=students.get(out.value.student_id, ""),
        linked_at=out.value.created_at,
    )
    return respond(view, replayed=out.replayed)


@router.get("/parent/students", response_model=p.LinkedStudentList)
async def list_linked_students(parent: ParentDep, services: ServicesDep) -> JSONResponse:
    rows = await services.parents.list_students(parent[0])
    return respond(
        p.LinkedStudentList(
            students=[
                p.LinkedStudent(student_id=c.student_id, display_name=n, linked_at=c.created_at)
                for c, n in rows
            ]
        )
    )


@router.get("/parent/students/{student_id}/summary", response_model=p.ParentSummaryView)
async def parent_summary(
    student_id: StudentPath, parent: ParentDep, services: ServicesDep
) -> JSONResponse:
    return respond(summary_view(await services.parents.summary(parent[0], student_id)))
