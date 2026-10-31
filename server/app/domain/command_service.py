"""Student commands that start agent work: submissions, messages, run input, cancel (Step 14).

Each command is one transaction: the student's content + Run(QUEUED) + idempotency record +
outbox entry + run.queued event. Nothing external happens inside it; dispatch to the queue
happens after commit (and again from the outbox scan if that first attempt is lost).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.access import require_course_access
from app.domain.commands import CommandKey, Outcome, find_replay, remember
from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.catalog import CourseCatalog
from app.domain.ports.repositories import Tx, UnitOfWork
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.runs import enqueue_run, finish_run
from app.domain.session_service import get_owned_session, with_active_run
from app.domain.types.actor import ActorContext, Permission
from app.domain.types.file import FileStatus
from app.domain.types.message import Message, MessageRole
from app.domain.types.outbox import RunInput
from app.domain.types.run import Run, RunKind, RunStatus
from app.domain.types.session import Session, SessionStatus
from app.domain.types.submission import Submission, SubmissionInput

SUBMISSION_RESOURCE = "submission"
MESSAGE_RESOURCE = "message"
RUN_RESOURCE = "run"


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptedSubmission:
    submission: Submission
    run: Run


@dataclass(frozen=True, slots=True, kw_only=True)
class AcceptedMessage:
    message: Message
    run: Run


class CommandService:
    def __init__(
        self, uow: UnitOfWork, catalog: CourseCatalog, clock: Clock, ids: IdFactory
    ) -> None:
        self._uow = uow
        self._catalog = catalog
        self._clock = clock
        self._ids = ids

    # ---- Shared checks ----------------------------------------------------------------

    async def _commandable_session(self, tx: Tx, actor: ActorContext, session_id: str) -> Session:
        session = await get_owned_session(tx, actor, session_id)
        if session.status is not SessionStatus.OPEN:
            raise DomainError(
                ErrorCode.INVALID_STATE_TRANSITION, f"Session is {session.status.value}."
            )
        await require_course_access(tx, actor, self._catalog, session.course_id)
        # Reading (and later writing) the Session document makes it the guard for the
        # one-nonterminal-Run rule: concurrent commands conflict and serialize.
        if session.active_run_id is not None:
            active = await tx.runs.get(actor, session.active_run_id)
            if active is not None and not active.is_terminal:
                raise DomainError(
                    ErrorCode.RUN_IN_PROGRESS, "A run is already active in this session."
                )
        return session

    async def _check_files(self, tx: Tx, actor: ActorContext, file_ids: Sequence[str]) -> None:
        for file_id in file_ids:
            stored = await tx.files.get(actor, file_id)
            if stored is None:
                raise DomainError(ErrorCode.NOT_FOUND, "File not found.")
            if stored.status is not FileStatus.READY:
                raise DomainError(ErrorCode.FILE_NOT_READY, "File has not finished uploading.")

    def _new_run(
        self,
        actor: ActorContext,
        session: Session,
        kind: RunKind,
        *,
        submission_id: str | None = None,
        message_id: str | None = None,
    ) -> Run:
        now = self._clock.now()
        return Run(
            run_id=self._ids.new("run"),
            student_id=actor.student_id,
            session_id=session.session_id,
            status=RunStatus.QUEUED,
            kind=kind,
            submission_id=submission_id,
            message_id=message_id,
            created_at=now,
            updated_at=now,
        )

    # ---- Submissions ------------------------------------------------------------------

    async def submit_answer(
        self,
        actor: ActorContext,
        session_id: str,
        submission_input: SubmissionInput,
        cmd: CommandKey,
    ) -> Outcome[AcceptedSubmission]:
        actor.require(Permission.LEARNING_COMMAND)

        async def write(tx: Tx) -> Outcome[AcceptedSubmission]:
            replay = await find_replay(tx, actor, cmd)
            if replay is not None:
                prior = await tx.submissions.get(actor, replay.resource_id)
                run = await tx.runs.get(actor, prior.run_id) if prior else None
                if prior is None or run is None:  # pragma: no cover - written atomically
                    raise DomainError(ErrorCode.NOT_FOUND, "Submission not found.")
                return Outcome(
                    value=AcceptedSubmission(submission=prior, run=run),
                    replayed=True,
                    created=False,
                )

            session = await self._commandable_session(tx, actor, session_id)
            question = self._catalog.question(session.course_id, submission_input.question_id)
            if question is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Question not found in this course.")
            if question.version != submission_input.question_version:
                raise DomainError(
                    ErrorCode.VALIDATION_FAILED, "questionVersion does not match the question."
                )
            if submission_input.supersedes_submission_id is not None:
                prior = await tx.submissions.get(actor, submission_input.supersedes_submission_id)
                if prior is None or prior.session_id != session_id:
                    raise DomainError(ErrorCode.NOT_FOUND, "Superseded submission not found.")
            await self._check_files(tx, actor, submission_input.answer.file_ids)

            now = self._clock.now()
            submission_id = self._ids.new("sub")
            run = self._new_run(
                actor, session, RunKind.ASSESS_SUBMISSION, submission_id=submission_id
            )
            submission = Submission(
                submission_id=submission_id,
                student_id=actor.student_id,
                session_id=session_id,
                question_id=submission_input.question_id,
                question_version=submission_input.question_version,
                answer=submission_input.answer,
                supersedes_submission_id=submission_input.supersedes_submission_id,
                run_id=run.run_id,
                created_at=now,
            )
            tx.submissions.create(actor, submission)
            entry = await enqueue_run(
                tx, actor, run, now=now, ids=self._ids, causation_id=submission_id
            )
            tx.sessions.save(
                actor, dataclasses.replace(with_active_run(session, run.run_id), updated_at=now)
            )
            remember(
                tx, actor, cmd, resource_type=SUBMISSION_RESOURCE,
                resource_id=submission_id, response_status=202, now=now,
            )  # fmt: skip
            return Outcome(
                value=AcceptedSubmission(submission=submission, run=run),
                delivery_id=entry.delivery_id,
            )

        return await self._uow.transaction(write)

    # ---- Messages ---------------------------------------------------------------------

    async def send_message(
        self,
        actor: ActorContext,
        session_id: str,
        *,
        text: str,
        file_ids: Sequence[str],
        cmd: CommandKey,
    ) -> Outcome[AcceptedMessage]:
        actor.require(Permission.LEARNING_COMMAND)

        async def write(tx: Tx) -> Outcome[AcceptedMessage]:
            replay = await find_replay(tx, actor, cmd)
            if replay is not None:
                prior = await tx.messages.get(actor, replay.resource_id)
                run = await tx.runs.get(actor, prior.run_id) if prior and prior.run_id else None
                if prior is None or run is None:  # pragma: no cover - written atomically
                    raise DomainError(ErrorCode.NOT_FOUND, "Message not found.")
                return Outcome(
                    value=AcceptedMessage(message=prior, run=run), replayed=True, created=False
                )

            session = await self._commandable_session(tx, actor, session_id)
            await self._check_files(tx, actor, file_ids)
            now = self._clock.now()
            message_id = self._ids.new("msg")
            run = self._new_run(actor, session, RunKind.HINT, message_id=message_id)
            message = Message(
                message_id=message_id,
                student_id=actor.student_id,
                session_id=session_id,
                role=MessageRole.STUDENT,
                text=text,
                file_ids=tuple(file_ids),
                run_id=run.run_id,
                created_at=now,
            )
            tx.messages.save(actor, message)
            entry = await enqueue_run(
                tx, actor, run, now=now, ids=self._ids, causation_id=message_id
            )
            tx.sessions.save(
                actor, dataclasses.replace(with_active_run(session, run.run_id), updated_at=now)
            )
            remember(
                tx, actor, cmd, resource_type=MESSAGE_RESOURCE,
                resource_id=message_id, response_status=202, now=now,
            )  # fmt: skip
            return Outcome(
                value=AcceptedMessage(message=message, run=run), delivery_id=entry.delivery_id
            )

        return await self._uow.transaction(write)

    # ---- Runs -------------------------------------------------------------------------

    async def get_run(self, actor: ActorContext, run_id: str) -> Run:
        actor.require(Permission.LEARNING_READ)

        async def read(tx: Tx) -> Run:
            run = await tx.runs.get(actor, run_id)
            if run is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Run not found.")
            return run

        return await self._uow.transaction(read)

    async def provide_input(
        self,
        actor: ActorContext,
        run_id: str,
        *,
        input_request_id: str,
        confirmed_text: str,
        cmd: CommandKey,
    ) -> Outcome[Run]:
        """Accept the typed value a WAITING_INPUT run asked for, then re-queue it."""
        actor.require(Permission.LEARNING_COMMAND)

        async def write(tx: Tx) -> Outcome[Run]:
            replay = await find_replay(tx, actor, cmd)
            if replay is not None:
                run = await tx.runs.get(actor, replay.resource_id)
                if run is None:  # pragma: no cover
                    raise DomainError(ErrorCode.NOT_FOUND, "Run not found.")
                return Outcome(value=run, replayed=True, created=False)

            run = await tx.runs.get(actor, run_id)
            if run is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Run not found.")
            if run.is_terminal:
                raise DomainError(ErrorCode.RUN_TERMINAL, f"Run is {run.status.value}.")
            if (
                run.status is not RunStatus.WAITING_INPUT
                or run.input_request is None
                or run.input_request.input_request_id != input_request_id
            ):
                raise DomainError(
                    ErrorCode.INVALID_STATE_TRANSITION,
                    "This run is not waiting for that input (stale or mismatched request).",
                )
            now = self._clock.now()
            tx.run_inputs.create(
                actor,
                RunInput(
                    input_request_id=input_request_id,
                    run_id=run_id,
                    student_id=actor.student_id,
                    confirmed_text=confirmed_text,
                    created_at=now,
                ),
            )
            requeued = dataclasses.replace(
                run,
                status=RunStatus.QUEUED,
                input_request=None,
                dispatch_generation=run.dispatch_generation + 1,
                updated_at=now,
            )
            entry = await enqueue_run(
                tx, actor, requeued, now=now, ids=self._ids, causation_id=input_request_id
            )
            remember(
                tx, actor, cmd, resource_type=RUN_RESOURCE,
                resource_id=run_id, response_status=202, now=now,
            )  # fmt: skip
            return Outcome(value=requeued, delivery_id=entry.delivery_id)

        return await self._uow.transaction(write)

    async def cancel_run(self, actor: ActorContext, run_id: str, cmd: CommandKey) -> Outcome[Run]:
        """Not-yet-leased runs are cancelled immediately. A RUNNING run is flagged and the
        worker persists CANCELLED at its next check (before tools and before commit)."""
        actor.require(Permission.LEARNING_COMMAND)

        async def write(tx: Tx) -> Outcome[Run]:
            replay = await find_replay(tx, actor, cmd)
            if replay is not None:
                run = await tx.runs.get(actor, replay.resource_id)
                if run is None:  # pragma: no cover
                    raise DomainError(ErrorCode.NOT_FOUND, "Run not found.")
                return Outcome(value=run, replayed=True, created=False)

            run = await tx.runs.get(actor, run_id)
            if run is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Run not found.")
            now = self._clock.now()
            if run.status is RunStatus.CANCELLED:
                return Outcome(value=run, created=False)
            if run.is_terminal:
                raise DomainError(ErrorCode.RUN_TERMINAL, f"Run already {run.status.value}.")
            if run.status is RunStatus.RUNNING:
                updated = dataclasses.replace(run, cancel_requested=True, updated_at=now)
                tx.runs.save(actor, updated)
            else:
                updated = await finish_run(
                    tx, actor, run, RunStatus.CANCELLED, now=now, ids=self._ids
                )
            remember(
                tx, actor, cmd, resource_type=RUN_RESOURCE,
                resource_id=run_id, response_status=202, now=now,
            )  # fmt: skip
            return Outcome(value=updated)

        return await self._uow.transaction(write)
