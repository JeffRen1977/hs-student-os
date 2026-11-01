"""Persistent, course-scoped Task lifecycle (Step 12). Reading tasks never replans."""

from __future__ import annotations

import dataclasses
from datetime import date
from zoneinfo import ZoneInfo

from app.domain.access import require_course_access
from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.catalog import CourseCatalog
from app.domain.ports.repositories import TaskQuery, Tx, UnitOfWork
from app.domain.ports.runtime import Clock
from app.domain.types.actor import ActorContext, Permission
from app.domain.types.common import PageRequest, PaginatedResponse
from app.domain.types.course import EnrollmentStatus
from app.domain.types.task import TASK_TRANSITIONS, Task, TaskPatch, TaskStatus
from app.domain.types.transitions import ensure_transition

TODAY = "today"


class TaskService:
    def __init__(self, uow: UnitOfWork, catalog: CourseCatalog, clock: Clock) -> None:
        self._uow = uow
        self._catalog = catalog
        self._clock = clock

    def local_today(self, timezone: str) -> date:
        return self._clock.now().astimezone(ZoneInfo(timezone)).date()

    async def list_tasks(
        self,
        actor: ActorContext,
        *,
        on: date | str | None,
        status: TaskStatus | None,
        course_id: str | None,
        page: PageRequest,
    ) -> PaginatedResponse[Task]:
        """`on` is a local date, `"today"` (resolved in the student's timezone), or None."""
        actor.require(Permission.LEARNING_READ)

        async def read(tx: Tx) -> PaginatedResponse[Task]:
            student = await tx.students.get(actor)
            if student is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Student not found.")
            scheduled = self.local_today(student.preferences.timezone) if on == TODAY else on
            if isinstance(scheduled, str):  # pragma: no cover - the route validates this
                raise DomainError(ErrorCode.VALIDATION_FAILED, "date must be YYYY-MM-DD or today")
            enrolled = sorted(
                e.course_id
                for e in await tx.enrollments.list(actor, status=EnrollmentStatus.ACTIVE)
            )
            # Tasks for unenrolled courses are hidden (but kept for re-enrollment).
            courses = [c for c in enrolled if course_id is None or c == course_id]
            query = TaskQuery(scheduled_date=scheduled, status=status, course_ids=courses)
            return await tx.tasks.list(actor, query, page)

        return await self._uow.transaction(read)

    async def get_task(self, actor: ActorContext, task_id: str) -> Task:
        actor.require(Permission.LEARNING_READ)

        async def read(tx: Tx) -> Task:
            task = await tx.tasks.get(actor, task_id)
            if task is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Task not found.")
            return task

        return await self._uow.transaction(read)

    async def patch_task(
        self, actor: ActorContext, task_id: str, patch: TaskPatch, *, expected_version: int
    ) -> Task:
        """Students may reschedule, lock, or skip (with a reason) a not-yet-started task.
        Completion is decided by the Session completion rules, never by a PATCH."""
        actor.require(Permission.LEARNING_COMMAND)
        if patch.scheduled_date is None and patch.student_locked is None and not patch.skip:
            raise DomainError(ErrorCode.VALIDATION_FAILED, "patch must change at least one field")

        async def write(tx: Tx) -> Task:
            task = await tx.tasks.get(actor, task_id)
            if task is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Task not found.")
            if task.version != expected_version:
                raise DomainError(ErrorCode.VERSION_CONFLICT, "The task changed since it was read.")
            await require_course_access(tx, actor, self._catalog, task.course_id)
            if task.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED):
                raise DomainError(ErrorCode.TASK_NOT_OPEN, f"Task is {task.status.value}.")
            status: TaskStatus = task.status
            if patch.skip:
                ensure_transition(TASK_TRANSITIONS, task.status, TaskStatus.SKIPPED, entity="Task")
                status = TaskStatus.SKIPPED
            # Moving a task is a student choice the planner must keep, so a new date
            # locks it unless the same patch says otherwise.
            locked = task.student_locked
            if patch.scheduled_date is not None and patch.scheduled_date != task.scheduled_date:
                locked = True
            if patch.student_locked is not None:
                locked = patch.student_locked
            updated = dataclasses.replace(
                task,
                status=status,
                version=task.version + 1,
                scheduled_date=patch.scheduled_date or task.scheduled_date,
                student_locked=locked,
                skip_reason=patch.skip_reason if patch.skip else task.skip_reason,
            )
            tx.tasks.save(actor, updated, now=self._clock.now())
            return updated

        return await self._uow.transaction(write)
