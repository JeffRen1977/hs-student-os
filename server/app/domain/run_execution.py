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
from app.domain.assessment_service import AssessmentRejectedError, AssessmentService
from app.domain.errors import ErrorCode
from app.domain.planner_service import PlannerService
from app.domain.ports.catalog import CourseCatalog
from app.domain.ports.execution import (
    ExecutionFailure,
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
from app.domain.types.session import Session, SessionStatus
from app.domain.types.student import Student

logger = logging.getLogger(__name__)

WORKER_SERVICE = "run-worker"
HISTORY_PAGE = 100
HISTORY_MAX_PAGES = 5  # the context loader truncates further to the pack's token budget


class ProcessResult(StrEnum):
    DONE = "done"  # acknowledge the delivery
    RETRY = "retry"  # ask the queue to redeliver later


@dataclass(frozen=True, slots=True, kw_only=True)
class LeaseGrant:
    token: int
    request: ExecutionRequest | None  # None for PLANNING runs: no model, no session


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
        assessments: AssessmentService | None = None,
        planner: PlannerService | None = None,
    ) -> None:
        self._uow = uow
        self._assessments = assessments
        self._planner = planner
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
        run_id = delivery.run_id
        if run_id is None:  # not a run delivery: nothing to execute
            return ProcessResult.DONE
        acquired = await self.acquire(actor, run_id)
        if isinstance(acquired, ProcessResult):
            return acquired
        if acquired.request is None:
            return await self._process_planning(actor, run_id, acquired.token)
        try:
            output = await self._executor.execute(acquired.request)
        except RetryableExecutionError:
            logger.warning("run_retryable_error", extra={"runId": run_id})
            return await self._after_retryable_error(actor, run_id, acquired.token)
        except ExecutionFailure as exc:
            logger.warning("run_execution_failed", extra={"runId": run_id,
                                                          "error": exc.code})  # fmt: skip
            await self.fail(actor, run_id, acquired.token, exc.code, False)
            return ProcessResult.DONE
        except Exception as exc:
            logger.exception(
                "run_execution_error",
                extra={"runId": run_id, "error": type(exc).__name__},
            )
            await self.fail(actor, run_id, acquired.token, "EXECUTION_FAILED", False)
            return ProcessResult.DONE
        try:
            await self.commit(actor, run_id, acquired.token, output)
        except AssessmentRejectedError as exc:
            # The commit transaction aborted as a whole: no assessment, no mastery change.
            logger.warning("assessment_rejected", extra={"runId": run_id,
                                                         "reason": exc.reason})  # fmt: skip
            await self.fail(actor, run_id, acquired.token, "ASSESSMENT_REJECTED", False)
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
            if run.kind is RunKind.PLANNING:
                return await self._lease_planning(tx, actor, run, now)
            if run.session_id is None:
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
            history = await self._history(tx, actor, session.session_id)
            submission = (
                await tx.submissions.get(actor, run.submission_id) if run.submission_id else None
            )
            student = await tx.students.get(actor)
            task = await tx.tasks.get(actor, session.task_id)
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
                    history=history,
                    submission=submission,
                    student_name=student.profile.display_name if student else "",
                    mastery_context=self._mastery_context(student, session),
                    mode=task.mode.value if task else "",
                ),
            )

        return await self._uow.transaction(body)

    async def _lease_planning(
        self, tx: Tx, actor: ActorContext, run: Run, now: datetime
    ) -> LeaseGrant | ProcessResult:
        if self._planner is None:
            await self._fail_in_tx(tx, actor, run, "UNSUPPORTED_RUN_KIND", now)
            return ProcessResult.DONE
        if run.attempt_count >= self._max_attempts:
            await self._fail_in_tx(tx, actor, run, "RUN_ATTEMPTS_EXHAUSTED", now)
            return ProcessResult.DONE
        token = run.lease_fencing_token + 1
        tx.runs.save(
            actor,
            dataclasses.replace(
                run,
                status=RunStatus.RUNNING,
                attempt_count=run.attempt_count + 1,
                lease_fencing_token=token,
                lease_owner=self._worker_id,
                lease_expires_at=now + self._lease,
                updated_at=now,
            ),
        )
        if run.status is RunStatus.QUEUED:
            await tx.events.append(
                actor,
                EventDraft(
                    type=EventType.RUN_STARTED,
                    causation_id=run.run_id,
                    run_id=run.run_id,
                    payload={"kind": run.kind.value},
                ),
                event_id=self._ids.new("evt"),
                now=now,
            )
        return LeaseGrant(token=token, request=None)

    async def _process_planning(
        self, actor: ActorContext, run_id: str, token: int
    ) -> ProcessResult:
        """Planning is deterministic and reads only stored state, so it runs entirely in
        the commit transaction: the plan, moved tasks, plan.updated and the Run's
        terminal state land together or not at all."""
        planner = self._planner
        assert planner is not None

        async def body(tx: Tx) -> bool:
            run = await self._current_if_ours(tx, actor, run_id, token)
            if run is None:
                return False
            now = self._clock.now()
            if run.cancel_requested:
                await finish_run(tx, actor, run, RunStatus.CANCELLED, now=now, ids=self._ids)
                return True
            plan = await planner.replan_in_tx(tx, actor, run, now)
            await finish_run(
                tx, actor, run, RunStatus.SUCCEEDED, now=now, ids=self._ids,
                result=RunResult(plan_id=plan.plan_id),
            )  # fmt: skip
            return True

        # A failed commit propagates like an assessment commit does: the lease expires,
        # recovery re-queues, and the attempt limit ends a deterministic failure.
        await self._uow.transaction(body)
        return ProcessResult.DONE

    async def _history(self, tx: Tx, actor: ActorContext, session_id: str) -> list[Message]:
        messages: list[Message] = []
        page = PageRequest(limit=HISTORY_PAGE)
        for _ in range(HISTORY_MAX_PAGES):
            batch = await tx.messages.list_for_session(actor, session_id, page)
            messages.extend(batch.items)
            if batch.next_cursor is None:
                break
            page = PageRequest(cursor=batch.next_cursor, limit=HISTORY_PAGE)
        return messages

    @staticmethod
    def _mastery_context(student: Student | None, session: Session) -> str:
        """Bounded summary of this course's mastery only (no other course's history)."""
        if student is None:
            return ""
        prefix = session.course_id + "."
        lines = [
            f"- {skill}: {m.level.value} ({m.independent_evidence_count} independent)"
            for skill, m in sorted(student.mastery_summary.items())
            if skill.startswith(prefix)
        ]
        return "\n".join(lines[:20])

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
            assessment_id: str | None = None
            if output.assessment is not None:
                if self._assessments is None:
                    raise AssessmentRejectedError("assessments_not_configured")
                for result in output.tool_results:
                    tx.tool_results.create(actor, result)
                assessment = await self._assessments.commit_assessment(
                    tx, actor, run, output.assessment,
                    tool_result_ids={t.tool_result_id for t in output.tool_results}, now=now,
                )  # fmt: skip
                assessment_id = assessment.assessment_id
            if output.issued_hint:
                session = await tx.sessions.get(actor, run.session_id)
                if session is not None:
                    tx.sessions.save(
                        actor,
                        dataclasses.replace(
                            session,
                            server_hint_count=session.server_hint_count + 1,
                            version=session.version + 1,
                            updated_at=now,
                        ),
                    )
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
                tx, actor, dataclasses.replace(run, usage_tokens=output.usage_tokens),
                RunStatus.SUCCEEDED, now=now, ids=self._ids,
                result=RunResult(message_id=message.message_id, assessment_id=assessment_id),
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
