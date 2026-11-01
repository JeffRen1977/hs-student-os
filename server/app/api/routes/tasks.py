"""Tasks (Step 12). GET never triggers replanning."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.api import presenters
from app.api.dependencies.auth import Actor, ServicesDep
from app.api.dependencies.commands import IfMatchHeader, expected_version
from app.api.responses import respond
from app.api.routes.params import COURSE_PATTERN, Cursor, IdPath, Limit, page
from app.domain.errors import DomainError, ErrorCode
from app.domain.task_service import TODAY
from app.domain.types.common import DEFAULT_PAGE_LIMIT
from app.domain.types.task import TaskPatch, TaskStatus
from app.schemas import task as t

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _parse_date(value: str | None) -> date | str | None:
    if value is None or value == TODAY:
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "date must be YYYY-MM-DD or today") from exc


@router.get("", response_model=t.TaskList)
async def list_tasks(
    actor: Actor,
    services: ServicesDep,
    date_: Annotated[str | None, Query(alias="date", max_length=10)] = None,
    status: TaskStatus | None = None,
    course_id: Annotated[str | None, Query(alias="courseId", pattern=COURSE_PATTERN)] = None,
    cursor: Cursor = None,
    limit: Limit = DEFAULT_PAGE_LIMIT,
) -> JSONResponse:
    result = await services.tasks.list_tasks(
        actor, on=_parse_date(date_), status=status, course_id=course_id, page=page(cursor, limit)
    )
    return respond(
        t.TaskList(tasks=[presenters.task(x) for x in result.items], next_cursor=result.next_cursor)
    )


@router.get("/{task_id}", response_model=t.Task)
async def get_task(task_id: IdPath, actor: Actor, services: ServicesDep) -> JSONResponse:
    task = await services.tasks.get_task(actor, task_id)
    return respond(presenters.task(task), etag=task.version)


@router.patch("/{task_id}", response_model=t.Task)
async def patch_task(
    task_id: IdPath,
    body: t.TaskPatchRequest,
    actor: Actor,
    services: ServicesDep,
    if_match: IfMatchHeader = None,
) -> JSONResponse:
    version = expected_version(if_match)
    patch = TaskPatch(
        scheduled_date=body.scheduled_date,
        student_locked=body.student_locked,
        skip=body.status is TaskStatus.SKIPPED,
        skip_reason=body.skip_reason,
    )
    task = await services.tasks.patch_task(actor, task_id, patch, expected_version=version)
    return respond(presenters.task(task), etag=task.version)
