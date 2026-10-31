"""Recoverable run execution with leases and fencing tokens (Step 15, BACKEND.md §5.3).

A delivery may arrive more than once, late, or after another worker took over. Safety
comes from the Run document, not the queue:

1. `acquire` transactionally takes a lease and increments the fencing token. Terminal runs
   are acknowledged with no effect; a live lease held by someone else means "retry later".
2. Execution happens outside any transaction.
3. `commit` re-reads the Run and writes only if the fencing token is still ours, so a stale
   worker can never overwrite a newer attempt or a cancellation.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.domain.access import is_enrolled, is_entitled
from app.domain.errors import ErrorCode
from app.domain.ports.catalog import CourseCatalog
from app.domain.ports.execution import (
    ExecutionOutput,
    ExecutionRequest,
    RetryableExecutionError,
    RunExecutor,
)
from app.domain.ports.repositories import EventDraft, Tx, UnitOfWork
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.runs import finish_run
from app.domain.types.actor import ActorContext, Permission
from app.domain.types.common import PageRequest
from app.domain.types.event import EventType
from app.domain.types.message import Message, MessageRole
from app.domain.types.outbox import Delivery
from app.domain.types.run import Run, RunError, RunKind, RunResult, RunStatus
from app.domain.types.session import SessionStatus

logger = logging.getLogger(__name__)

WORKER_SERVICE = "run-worker"
HISTORY_LIMIT = 20


class ProcessResult(StrEnum):
    DONE = "done"  # acknowledge the delivery
    RETRY = "retry"  # ask the queue to redeliver later


@dataclass(frozen=True, slots=True, kw_only=True)
class LeaseGrant:
    token: int
    request: ExecutionRequest


class RunExecutionService:
    def __init__(
        self,
        uow: UnitOfWork,
        catalog: CourseCatalog,
        executor: RunExecutor,
        clock: Clock,
        ids: IdFactory,
        *,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int,
    ) -> None:
        self._uow = uow
        self._catalog = catalog
        self._executor = executor
        self._clock = clock
        self._ids = ids
        self._worker_id = worker_id
        self._lease = timedelta(seconds=lease_seconds)
        self._max_attempts = max_attempts

    def actor_for(self, student_id: str) -> ActorContext:
        return ActorContext.for_service(WORKER_SERVICE, student_id)

    async def process(self, delivery: Delivery) -> ProcessResult:
        actor = self.actor_for(delivery.student_id)
        actor.require(Permission.RUN_EXECUTE)
        acquired = await self.acquire(actor, delivery.run_id)
        if isinstance(acquired, ProcessResult):
            return acquired
        try:
            output = await self._executor.execute(acquired.request)
        except RetryableExecutionError:
            logger.warning("run_retryable_error", extra={"runId": delivery.run_id})
            return await self._after_retryable_error(actor, delivery.run_id, acquired.token)
        except Exception as exc:
            logger.exception(
                "run_execution_error",
                extra={"runId": delivery.run_id, "error": type(exc).__name__},
            )
            await self.fail(actor, delivery.run_id, acquired.token, "EXECUTION_FAILED", False)
            return ProcessResult.DONE
        await self.commit(actor, delivery.run_id, acquired.token, output)
        return ProcessResult.DONE

    # ---- Lease ------------------------------------------------------------------------

    async def acquire(self, actor: ActorContext, run_id: str) -> LeaseGrant | ProcessResult:
        async def body(tx: Tx) -> LeaseGrant | ProcessResult:
            now = self._clock.now()
            run = await tx.runs.get(actor, run_id)
            if run is None or run.is_terminal or run.status is RunStatus.WAITING_INPUT:
                return ProcessResult.DONE  # duplicate/obsolete delivery: no effect
            if run.lease_active(now):
                return ProcessResult.RETRY  # another worker holds a live lease
            if run.cancel_requested:
                await finish_run(tx, actor, run, RunStatus.CANCELLED, now=now, ids=self._ids)
                return ProcessResult.DONE
            if run.session_id is None:  # PLANNING runs arrive with the planner (M3/M4)
                await self._fail_in_tx(tx, actor, run, "UNSUPPORTED_RUN_KIND", now)
                return ProcessResult.DONE
            session = await tx.sessions.get(actor, run.session_id)
            course = self._catalog.get(session.course_id) if session else None
            if session is None or session.status is not SessionStatus.OPEN or course is None:
                await self._fail_in_tx(tx, actor, run, "SESSION_NOT_OPEN", now)
                return ProcessResult.DONE
            # Verify course access again: the student may have lost access since enqueue.
            entitlements = await tx.students.get_entitlements(actor)
            enrollment = await tx.enrollments.get(actor, course.course_id)
            if not course.is_active or not is_entitled(entitlements, course):
                await self._fail_in_tx(tx, actor, run, ErrorCode.COURSE_ACCESS_REQUIRED, now)
                return ProcessResult.DONE
            if not is_enrolled(enrollment):
                await self._fail_in_tx(tx, actor, run, ErrorCode.COURSE_NOT_ENROLLED, now)
                return ProcessResult.DONE
            if run.attempt_count >= self._max_attempts:
                await self._fail_in_tx(tx, actor, run, "RUN_ATTEMPTS_EXHAUSTED", now)
                return ProcessResult.DONE

            student_text = await self._student_text(tx, actor, run)
            history = await tx.messages.list_for_session(
                actor, session.session_id, PageRequest(limit=HISTORY_LIMIT)
            )
            token = run.lease_fencing_token + 1
            leased = dataclasses.replace(
                run,
                status=RunStatus.RUNNING,
                attempt_count=run.attempt_count + 1,
                lease_fencing_token=token,
                lease_owner=self._worker_id,
                lease_expires_at=now + self._lease,
                updated_at=now,
            )
            tx.runs.save(actor, leased)
            if run.status is RunStatus.QUEUED:
                await tx.events.append(
                    actor,
                    EventDraft(
                        type=EventType.RUN_STARTED,
                        causation_id=run.run_id,
                        session_id=run.session_id,
                        run_id=run.run_id,
                        payload={"kind": run.kind.value},
                    ),
                    event_id=self._ids.new("evt"),
                    now=now,
                )
            return LeaseGrant(
                token=token,
                request=ExecutionRequest(
                    run=leased,
                    session=session,
                    course=course,
                    student_text=student_text,
                    history=history.items,
                ),
            )

        return await self._uow.transaction(body)

    async def _student_text(self, tx: Tx, actor: ActorContext, run: Run) -> str:
        if run.kind is RunKind.ASSESS_SUBMISSION and run.submission_id:
            submission = await tx.submissions.get(actor, run.submission_id)
            return submission.answer.text if submission else ""
        if run.kind is RunKind.HINT and run.message_id:
            message = await tx.messages.get(actor, run.message_id)
            return message.text if message else ""
        return ""

    # ---- Commit -----------------------------------------------------------------------

    async def _current_if_ours(
        self, tx: Tx, actor: ActorContext, run_id: str, token: int
    ) -> Run | None:
        run = await tx.runs.get(actor, run_id)
        if run is None or run.status is not RunStatus.RUNNING or run.lease_fencing_token != token:
            logger.info("stale_worker_commit_rejected", extra={"runId": run_id})
            return None
        return run

    async def commit(
        self, actor: ActorContext, run_id: str, token: int, output: ExecutionOutput
    ) -> bool:
        """Persist the result only if this worker still holds the newest lease."""

        async def body(tx: Tx) -> bool:
            run = await self._current_if_ours(tx, actor, run_id, token)
            if run is None:
                return False
            now = self._clock.now()
            if run.cancel_requested:
                await finish_run(tx, actor, run, RunStatus.CANCELLED, now=now, ids=self._ids)
                return True
            assert run.session_id is not None
            message = Message(
                message_id=self._ids.new("msg"),
                student_id=actor.student_id,
                session_id=run.session_id,
                role=MessageRole.AGENT,
                text=output.agent_text,
                run_id=run.run_id,
                created_at=now,
                synthetic=output.synthetic,
            )
            tx.messages.save(actor, message)
            await finish_run(
                tx, actor, run, RunStatus.SUCCEEDED, now=now, ids=self._ids,
                result=RunResult(message_id=message.message_id),
            )  # fmt: skip
            return True

        return await self._uow.transaction(body)

    async def fail(
        self, actor: ActorContext, run_id: str, token: int, code: str, retryable: bool
    ) -> bool:
        async def body(tx: Tx) -> bool:
            run = await self._current_if_ours(tx, actor, run_id, token)
            if run is None:
                return False
            await self._fail_in_tx(tx, actor, run, code, self._clock.now(), retryable=retryable)
            return True

        return await self._uow.transaction(body)

    async def _fail_in_tx(
        self,
        tx: Tx,
        actor: ActorContext,
        run: Run,
        code: str,
        now: datetime,
        *,
        retryable: bool = False,
    ) -> None:
        if run.status is RunStatus.QUEUED:
            # QUEUED → FAILED is not a transition; record the start, then fail.
            run = dataclasses.replace(run, status=RunStatus.RUNNING)
        await finish_run(
            tx, actor, run, RunStatus.FAILED, now=now, ids=self._ids,
            error=RunError(code=str(code), retryable=retryable),
        )  # fmt: skip

    async def _after_retryable_error(
        self, actor: ActorContext, run_id: str, token: int
    ) -> ProcessResult:
        async def body(tx: Tx) -> ProcessResult:
            run = await self._current_if_ours(tx, actor, run_id, token)
            if run is None:
                return ProcessResult.DONE
            now = self._clock.now()
            if run.attempt_count >= self._max_attempts:
                await self._fail_in_tx(tx, actor, run, "EXECUTION_RETRIES_EXHAUSTED", now)
                return ProcessResult.DONE
            # Release the lease early so the redelivery can take over immediately.
            tx.runs.save(
                actor,
                dataclasses.replace(run, lease_expires_at=now, lease_owner=None, updated_at=now),
            )
            return ProcessResult.RETRY

        return await self._uow.transaction(body)
