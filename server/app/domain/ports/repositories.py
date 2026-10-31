from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

from app.domain.types.actor import ActorContext
from app.domain.types.assessment import Assessment
from app.domain.types.common import IdempotencyRecord, PageRequest, PaginatedResponse
from app.domain.types.course import CourseEnrollment
from app.domain.types.event import DomainEvent
from app.domain.types.run import Run
from app.domain.types.session import Session
from app.domain.types.student import Entitlements, Student
from app.domain.types.submission import Submission
from app.domain.types.task import Task, TaskPatch


class StudentRepository(Protocol):
    async def get(self, actor: ActorContext) -> Student | None: ...

    async def get_entitlements(self, actor: ActorContext) -> Entitlements: ...

    async def update_twin(
        self, actor: ActorContext, *, expected_version: int, changes: dict[str, object]
    ) -> Student:
        """Apply whitelisted leaf-field changes; raise VERSION_CONFLICT on stale version."""
        ...


class CourseRepository(Protocol):
    async def list_enrollments(self, actor: ActorContext) -> Sequence[CourseEnrollment]: ...

    async def get_enrollment(
        self, actor: ActorContext, course_id: str
    ) -> CourseEnrollment | None: ...


class TaskRepository(Protocol):
    async def get(self, actor: ActorContext, task_id: str) -> Task | None: ...

    async def list_for_date(
        self, actor: ActorContext, local_date: date, page: PageRequest
    ) -> PaginatedResponse[Task]: ...

    async def patch(
        self, actor: ActorContext, task_id: str, *, expected_version: int, patch: TaskPatch
    ) -> Task: ...


class SessionRepository(Protocol):
    async def get(self, actor: ActorContext, session_id: str) -> Session | None: ...

    async def find_open_for_task(self, actor: ActorContext, task_id: str) -> Session | None: ...

    async def list_for_task(
        self, actor: ActorContext, task_id: str, page: PageRequest
    ) -> PaginatedResponse[Session]: ...


class RunRepository(Protocol):
    async def get(self, actor: ActorContext, run_id: str) -> Run | None: ...

    async def find_active_for_session(self, actor: ActorContext, session_id: str) -> Run | None: ...


class SubmissionRepository(Protocol):
    async def get(self, actor: ActorContext, submission_id: str) -> Submission | None: ...

    async def list_for_session(
        self, actor: ActorContext, session_id: str, page: PageRequest
    ) -> PaginatedResponse[Submission]: ...


class AssessmentRepository(Protocol):
    async def get(self, actor: ActorContext, assessment_id: str) -> Assessment | None: ...

    async def list_for_session(
        self, actor: ActorContext, session_id: str, page: PageRequest
    ) -> PaginatedResponse[Assessment]: ...


class EventRepository(Protocol):
    async def list_after(
        self, actor: ActorContext, after_sequence: int, limit: int
    ) -> Sequence[DomainEvent]:
        """Events with sequence > after_sequence, ascending. EVENT_CURSOR_EXPIRED if purged."""
        ...

    async def latest_sequence(self, actor: ActorContext) -> int: ...


class IdempotencyRepository(Protocol):
    async def get(self, actor: ActorContext, scope: str, key: str) -> IdempotencyRecord | None: ...
