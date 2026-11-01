"""Run state changes shared by the command service and the worker.

Every terminal transition goes through `finish_run`, which also frees the Session's
execution slot, so `Session.active_run_id` and Run status never drift apart.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

from app.domain.ports.repositories import EventDraft, Tx
from app.domain.ports.runtime import IdFactory
from app.domain.session_service import with_active_run
from app.domain.types.actor import ActorContext
from app.domain.types.event import EventType
from app.domain.types.outbox import OutboxEntry, OutboxStatus
from app.domain.types.run import RUN_TRANSITIONS, Run, RunError, RunKind, RunResult, RunStatus
from app.domain.types.transitions import ensure_transition

_TERMINAL_EVENTS = {
    RunStatus.SUCCEEDED: EventType.RUN_COMPLETED,
    RunStatus.FAILED: EventType.RUN_FAILED,
    RunStatus.CANCELLED: EventType.RUN_CANCELLED,
}


async def enqueue_run(
    tx: Tx, actor: ActorContext, run: Run, *, now: datetime, ids: IdFactory, causation_id: str
) -> OutboxEntry:
    """Persist a QUEUED run together with its outbox entry and run.queued event."""
    tx.runs.save(actor, run)
    entry = OutboxEntry(
        delivery_id=run.delivery_id,
        student_id=actor.student_id,
        run_id=run.run_id,
        status=OutboxStatus.PENDING,
        created_at=now,
    )
    tx.outbox.save(actor, entry)
    await tx.events.append(
        actor,
        EventDraft(
            type=EventType.RUN_QUEUED,
            causation_id=causation_id,
            session_id=run.session_id,
            run_id=run.run_id,
            payload={"kind": run.kind.value},
        ),
        event_id=ids.new("evt"),
        now=now,
    )
    return entry


async def finish_run(
    tx: Tx,
    actor: ActorContext,
    run: Run,
    status: RunStatus,
    *,
    now: datetime,
    ids: IdFactory,
    result: RunResult | None = None,
    error: RunError | None = None,
) -> Run:
    ensure_transition(RUN_TRANSITIONS, run.status, status, entity="Run")
    finished = dataclasses.replace(
        run,
        status=status,
        result=result if status is RunStatus.SUCCEEDED else None,
        error=error if status is RunStatus.FAILED else None,
        input_request=None,
        lease_owner=None,
        lease_expires_at=None,
        updated_at=now,
    )
    tx.runs.save(actor, finished)
    if run.session_id is not None:
        session = await tx.sessions.get(actor, run.session_id)
        if session is not None and session.active_run_id == run.run_id:
            tx.sessions.save(
                actor, dataclasses.replace(with_active_run(session, None), updated_at=now)
            )
    if run.kind is RunKind.PLANNING:
        state = await tx.plans.get_state(actor)
        if state.active_run_id == run.run_id:
            tx.plans.save_state(
                actor, dataclasses.replace(state, active_run_id=None, version=state.version + 1)
            )
    payload: dict[str, object] = {"kind": run.kind.value}
    if error is not None:
        payload |= {"errorCode": error.code, "retryable": error.retryable}
    await tx.events.append(
        actor,
        EventDraft(
            type=_TERMINAL_EVENTS[status],
            causation_id=run.run_id,
            session_id=run.session_id,
            run_id=run.run_id,
            payload=payload,
        ),
        event_id=ids.new("evt"),
        now=now,
    )
    return finished
