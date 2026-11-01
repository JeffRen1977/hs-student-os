"""Sessions: the per-course agent conversation boundary (Step 13)."""

from __future__ import annotations

import dataclasses

from app.domain.access import require_course_access
from app.domain.commands import CommandKey, Outcome, find_replay, remember
from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.catalog import CourseCatalog
from app.domain.ports.content import SubjectPackRegistry
from app.domain.ports.repositories import EventDraft, SessionQuery, Tx, UnitOfWork
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.types.actor import ActorContext, Permission
from app.domain.types.common import PageRequest, PaginatedResponse
from app.domain.types.event import EventType
from app.domain.types.message import Message
from app.domain.types.session import (
    SESSION_TRANSITIONS,
    ContextVersion,
    Session,
    SessionActivity,
    SessionStatus,
    completion_for,
)
from app.domain.types.submission import Submission
from app.domain.types.task import TASK_TRANSITIONS, TaskStatus
from app.domain.types.transitions import ensure_transition

SESSION_RESOURCE = "session"
UNVERSIONED_WORKFLOW = "unversioned"


async def get_owned_session(tx: Tx, actor: ActorContext, session_id: str) -> Session:
    session = await tx.sessions.get(actor, session_id)
    if session is None:
        raise DomainError(ErrorCode.NOT_FOUND, "Session not found.")
    return session


def with_active_run(session: Session, run_id: str | None) -> Session:
    return dataclasses.replace(
        session,
        active_run_id=run_id,
        version=session.version + 1,
        completion=completion_for(session.status, run_id, session.has_accepted_assessment),
    )


class SessionService:
    def __init__(
        self,
        uow: UnitOfWork,
        catalog: CourseCatalog,
        clock: Clock,
        ids: IdFactory,
        packs: SubjectPackRegistry | None = None,
    ) -> None:
        self._uow = uow
        self._catalog = catalog
        self._clock = clock
        self._ids = ids
        self._packs = packs

    def _activity(self, course_id: str, question_id: str | None) -> SessionActivity | None:
        """Pin the task's question and rubric versions for the whole session (Step 17.1)."""
        if question_id is None:
            return None
        question = self._packs.question(course_id, question_id) if self._packs else None
        if question is None:
            # Missing, or withheld because it has not been content-reviewed.
            raise DomainError(
                ErrorCode.COURSE_NOT_AVAILABLE, "This task's practice content is not available."
            )
        return SessionActivity(
            question_id=question.question_id,
            question_version=question.version,
            rubric_id=question.rubric_id,
            rubric_version=question.rubric_version,
        )

    async def create_session(
        self, actor: ActorContext, task_id: str, cmd: CommandKey
    ) -> Outcome[Session]:
        """Start (or resume) the one OPEN Session for a Task.

        Course, agent, mode and skills come from the stored Task and the pinned pack, never
        from the request.
        """
        actor.require(Permission.LEARNING_COMMAND)

        async def write(tx: Tx) -> Outcome[Session]:
            replay = await find_replay(tx, actor, cmd)
            if replay is not None:
                session = await get_owned_session(tx, actor, replay.resource_id)
                return Outcome(value=session, replayed=True, created=replay.response_status == 201)

            task = await tx.tasks.get(actor, task_id)
            if task is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Task not found.")
            course = await require_course_access(tx, actor, self._catalog, task.course_id)
            if task.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED):
                raise DomainError(
                    ErrorCode.TASK_NOT_OPEN,
                    f"Task is {task.status.value}; new practice needs a new task.",
                )
            now = self._clock.now()

            # The Task document is the uniqueness guard: concurrent starts both read and
            # write it, so the transaction serializes them into one OPEN Session.
            if task.open_session_id is not None:
                existing = await tx.sessions.get(actor, task.open_session_id)
                if existing is not None and existing.status is SessionStatus.OPEN:
                    remember(
                        tx, actor, cmd, resource_type=SESSION_RESOURCE,
                        resource_id=existing.session_id, response_status=200, now=now,
                    )  # fmt: skip
                    return Outcome(value=existing, created=False)

            activity = self._activity(task.course_id, task.question_id)
            session = Session(
                session_id=self._ids.new("sess"),
                student_id=actor.student_id,
                task_id=task.task_id,
                course_id=task.course_id,
                status=SessionStatus.OPEN,
                active_run_id=None,
                context_version=ContextVersion(
                    pack=course.pack_version,
                    workflow=course.workflow_version or UNVERSIONED_WORKFLOW,
                ),
                completion=completion_for(SessionStatus.OPEN, None, False),
                version=1,
                agent_skills=tuple(course.skills),
                activity=activity,
                created_at=now,
                updated_at=now,
            )
            tx.sessions.save(actor, session)
            if task.status is TaskStatus.PLANNED:
                ensure_transition(
                    TASK_TRANSITIONS, task.status, TaskStatus.IN_PROGRESS, entity="Task"
                )
            tx.tasks.save(
                actor,
                dataclasses.replace(
                    task,
                    status=TaskStatus.IN_PROGRESS,
                    open_session_id=session.session_id,
                    version=task.version + 1,
                ),
                now=now,
            )
            await tx.events.append(
                actor,
                EventDraft(
                    type=EventType.SESSION_STARTED,
                    causation_id=task.task_id,
                    session_id=session.session_id,
                    payload={"taskId": task.task_id},
                ),
                event_id=self._ids.new("evt"),
                now=now,
            )
            remember(
                tx, actor, cmd, resource_type=SESSION_RESOURCE,
                resource_id=session.session_id, response_status=201, now=now,
            )  # fmt: skip
            return Outcome(value=session)

        return await self._uow.transaction(write)

    async def abandon_session(
        self, actor: ActorContext, session_id: str, cmd: CommandKey
    ) -> Outcome[Session]:
        """OPEN → ABANDONED; the unfinished Task returns to PLANNED. Never claims completion."""
        actor.require(Permission.LEARNING_COMMAND)

        async def write(tx: Tx) -> Outcome[Session]:
            replay = await find_replay(tx, actor, cmd)
            if replay is not None:
                session = await get_owned_session(tx, actor, replay.resource_id)
                return Outcome(value=session, replayed=True, created=False)

            session = await get_owned_session(tx, actor, session_id)
            now = self._clock.now()
            if session.status is SessionStatus.ABANDONED:
                remember(
                    tx, actor, cmd, resource_type=SESSION_RESOURCE,
                    resource_id=session_id, response_status=200, now=now,
                )  # fmt: skip
                return Outcome(value=session, created=False)
            ensure_transition(
                SESSION_TRANSITIONS, session.status, SessionStatus.ABANDONED, entity="Session"
            )
            if session.active_run_id is not None:
                run = await tx.runs.get(actor, session.active_run_id)
                if run is not None and not run.is_terminal:
                    raise DomainError(
                        ErrorCode.RUN_IN_PROGRESS, "Cancel the active run before abandoning."
                    )
            abandoned = dataclasses.replace(
                session,
                status=SessionStatus.ABANDONED,
                active_run_id=None,
                version=session.version + 1,
                completion=completion_for(
                    SessionStatus.ABANDONED, None, session.has_accepted_assessment
                ),
                updated_at=now,
            )
            tx.sessions.save(actor, abandoned)
            task = await tx.tasks.get(actor, session.task_id)
            if task is not None and task.open_session_id == session_id:
                tx.tasks.save(
                    actor,
                    dataclasses.replace(
                        task,
                        status=(
                            TaskStatus.PLANNED
                            if task.status is TaskStatus.IN_PROGRESS
                            else task.status
                        ),
                        open_session_id=None,
                        version=task.version + 1,
                    ),
                    now=now,
                )
            await tx.events.append(
                actor,
                EventDraft(
                    type=EventType.SESSION_ABANDONED,
                    causation_id=session_id,
                    session_id=session_id,
                    payload={"taskId": session.task_id},
                ),
                event_id=self._ids.new("evt"),
                now=now,
            )
            remember(
                tx, actor, cmd, resource_type=SESSION_RESOURCE,
                resource_id=session_id, response_status=200, now=now,
            )  # fmt: skip
            return Outcome(value=abandoned)

        return await self._uow.transaction(write)

    # ---- Reads ------------------------------------------------------------------------

    async def get_session(self, actor: ActorContext, session_id: str) -> Session:
        actor.require(Permission.LEARNING_READ)

        async def read(tx: Tx) -> Session:
            return await get_owned_session(tx, actor, session_id)

        return await self._uow.transaction(read)

    async def list_sessions(
        self, actor: ActorContext, query: SessionQuery, page: PageRequest
    ) -> PaginatedResponse[Session]:
        actor.require(Permission.LEARNING_READ)

        async def read(tx: Tx) -> PaginatedResponse[Session]:
            return await tx.sessions.list(actor, query, page)

        return await self._uow.transaction(read)

    async def list_messages(
        self, actor: ActorContext, session_id: str, page: PageRequest
    ) -> PaginatedResponse[Message]:
        actor.require(Permission.LEARNING_READ)

        async def read(tx: Tx) -> PaginatedResponse[Message]:
            await get_owned_session(tx, actor, session_id)
            return await tx.messages.list_for_session(actor, session_id, page)

        return await self._uow.transaction(read)

    async def list_submissions(
        self, actor: ActorContext, session_id: str, page: PageRequest
    ) -> PaginatedResponse[Submission]:
        actor.require(Permission.LEARNING_READ)

        async def read(tx: Tx) -> PaginatedResponse[Submission]:
            await get_owned_session(tx, actor, session_id)
            return await tx.submissions.list_for_session(actor, session_id, page)

        return await self._uow.transaction(read)

    async def get_submission(self, actor: ActorContext, submission_id: str) -> Submission:
        actor.require(Permission.LEARNING_READ)

        async def read(tx: Tx) -> Submission:
            submission = await tx.submissions.get(actor, submission_id)
            if submission is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Submission not found.")
            return submission

        return await self._uow.transaction(read)
