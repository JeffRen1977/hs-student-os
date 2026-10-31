"""Transaction-scoped repository protocols.

All learning-data access happens inside `UnitOfWork.transaction(fn)`. The callback gets a
`Tx` whose stores read through the transaction and buffer writes until commit, so a
command's Submission + Run + idempotency record + outbox entry + events land atomically or
not at all (CLAUDE.md §2.4). The callback may be retried on contention: it must not call
external services and must derive every write from what it read.

Every store method takes an ActorContext and is scoped to `actor.student_id`; another
student's resources are simply absent (callers turn that into 404).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from app.domain.types.actor import ActorContext
from app.domain.types.common import IdempotencyRecord, PageRequest, PaginatedResponse
from app.domain.types.course import CourseEnrollment, EnrollmentStatus
from app.domain.types.event import DomainEvent, EventType
from app.domain.types.file import StoredFile
from app.domain.types.message import Message
from app.domain.types.outbox import OutboxEntry, RunInput
from app.domain.types.run import Run
from app.domain.types.session import Session, SessionStatus
from app.domain.types.student import Entitlements, Student
from app.domain.types.submission import Submission
from app.domain.types.task import Task, TaskStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskQuery:
    scheduled_date: date | None = None
    status: TaskStatus | None = None
    course_ids: Sequence[str] | None = None  # None = no course filter; () = nothing matches


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionQuery:
    task_id: str | None = None
    course_id: str | None = None
    status: SessionStatus | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class EventDraft:
    type: EventType
    causation_id: str | None
    session_id: str | None = None
    run_id: str | None = None
    payload: Mapping[str, object] | None = None


class StudentStore(Protocol):
    async def get(self, actor: ActorContext) -> Student | None: ...

    async def get_entitlements(self, actor: ActorContext) -> Entitlements: ...

    def save_twin(self, actor: ActorContext, student: Student, *, now: datetime) -> None:
        """Persist profile/goals/preferences/version. Never touches entitlements."""
        ...


class EnrollmentStore(Protocol):
    async def get(self, actor: ActorContext, course_id: str) -> CourseEnrollment | None: ...

    async def list(
        self, actor: ActorContext, *, status: EnrollmentStatus | None = None
    ) -> Sequence[CourseEnrollment]: ...

    def save(self, actor: ActorContext, enrollment: CourseEnrollment) -> None: ...


class TaskStore(Protocol):
    async def get(self, actor: ActorContext, task_id: str) -> Task | None: ...

    async def list(
        self, actor: ActorContext, query: TaskQuery, page: PageRequest
    ) -> PaginatedResponse[Task]: ...

    def save(self, actor: ActorContext, task: Task, *, now: datetime) -> None: ...


class SessionStore(Protocol):
    async def get(self, actor: ActorContext, session_id: str) -> Session | None: ...

    async def list(
        self, actor: ActorContext, query: SessionQuery, page: PageRequest
    ) -> PaginatedResponse[Session]: ...

    def save(self, actor: ActorContext, session: Session) -> None: ...


class MessageStore(Protocol):
    async def get(self, actor: ActorContext, message_id: str) -> Message | None: ...

    async def list_for_session(
        self, actor: ActorContext, session_id: str, page: PageRequest
    ) -> PaginatedResponse[Message]: ...

    def save(self, actor: ActorContext, message: Message) -> None: ...


class SubmissionStore(Protocol):
    async def get(self, actor: ActorContext, submission_id: str) -> Submission | None: ...

    async def list_for_session(
        self, actor: ActorContext, session_id: str, page: PageRequest
    ) -> PaginatedResponse[Submission]: ...

    def create(self, actor: ActorContext, submission: Submission) -> None:
        """Submissions are immutable: written once, never updated."""
        ...


class RunStore(Protocol):
    async def get(self, actor: ActorContext, run_id: str) -> Run | None: ...

    def save(self, actor: ActorContext, run: Run) -> None: ...


class RunInputStore(Protocol):
    def create(self, actor: ActorContext, run_input: RunInput) -> None: ...


class FileStore(Protocol):
    async def get(self, actor: ActorContext, file_id: str) -> StoredFile | None: ...


class IdempotencyStore(Protocol):
    async def get(self, actor: ActorContext, key_hash: str) -> IdempotencyRecord | None: ...

    def save(self, actor: ActorContext, record: IdempotencyRecord) -> None: ...


class EventStore(Protocol):
    async def append(
        self, actor: ActorContext, draft: EventDraft, *, event_id: str, now: datetime
    ) -> DomainEvent:
        """Assign the next per-student sequence and buffer the event in this transaction."""
        ...

    async def latest_sequence(self, actor: ActorContext) -> int: ...

    async def list_after(
        self, actor: ActorContext, after_sequence: int, limit: int
    ) -> Sequence[DomainEvent]: ...


class OutboxStore(Protocol):
    async def get(self, actor: ActorContext, delivery_id: str) -> OutboxEntry | None: ...

    def save(self, actor: ActorContext, entry: OutboxEntry) -> None: ...


class Tx(Protocol):
    @property
    def students(self) -> StudentStore: ...
    @property
    def enrollments(self) -> EnrollmentStore: ...
    @property
    def tasks(self) -> TaskStore: ...
    @property
    def sessions(self) -> SessionStore: ...
    @property
    def messages(self) -> MessageStore: ...
    @property
    def submissions(self) -> SubmissionStore: ...
    @property
    def runs(self) -> RunStore: ...
    @property
    def run_inputs(self) -> RunInputStore: ...
    @property
    def files(self) -> FileStore: ...
    @property
    def idempotency(self) -> IdempotencyStore: ...
    @property
    def events(self) -> EventStore: ...
    @property
    def outbox(self) -> OutboxStore: ...


class UnitOfWork(Protocol):
    async def transaction[T](self, fn: Callable[[Tx], Awaitable[T]]) -> T:
        """Run `fn` in one atomic transaction; all buffered writes commit or none do."""
        ...


class IdentityDirectory(Protocol):
    """Maps a verified auth subject (uid) to a stable studentId. Not actor-scoped: it runs
    before any actor exists, and only after the token has been verified."""

    async def resolve(self, uid: str) -> str | None: ...


class OperationsStore(Protocol):
    """Cross-student scans for service-only background jobs (dispatch and recovery)."""

    async def pending_outbox(self, limit: int) -> Sequence[OutboxEntry]: ...

    async def stalled_runs(
        self, *, queued_before: datetime, lease_expired_before: datetime, limit: int
    ) -> Sequence[Run]: ...
