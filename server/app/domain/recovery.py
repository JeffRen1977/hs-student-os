"""Re-queue runs whose delivery was lost or whose worker died (Step 15).

The outbox covers "committed but never dispatched". This scan covers the rest: a QUEUED
run nobody picked up (queue lost the message) and a RUNNING run whose lease expired
(worker crashed). Both get a fresh dispatch generation and a new outbox entry; the lease
and fencing token keep any late original delivery harmless.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

from app.domain.ports.repositories import OperationsStore, Tx, UnitOfWork
from app.domain.ports.runtime import Clock
from app.domain.types.actor import ActorContext
from app.domain.types.outbox import OutboxEntry, OutboxStatus
from app.domain.types.run import RunStatus

RECOVERY_SERVICE = "run-recovery"


class RecoveryService:
    def __init__(
        self,
        uow: UnitOfWork,
        operations: OperationsStore,
        clock: Clock,
        *,
        requeue_after_seconds: int,
    ) -> None:
        self._uow = uow
        self._ops = operations
        self._clock = clock
        self._requeue_after = timedelta(seconds=requeue_after_seconds)

    async def requeue_stalled(self, limit: int = 100) -> int:
        now = self._clock.now()
        queued_before = now - self._requeue_after
        candidates = await self._ops.stalled_runs(
            queued_before=queued_before, lease_expired_before=now, limit=limit
        )
        requeued = 0
        for candidate in candidates:
            actor = ActorContext.for_service(RECOVERY_SERVICE, candidate.student_id)

            async def body(
                tx: Tx, run_id: str = candidate.run_id, actor: ActorContext = actor
            ) -> bool:
                run = await tx.runs.get(actor, run_id)
                if run is None or run.is_terminal:
                    return False
                stalled_queue = (
                    run.status is RunStatus.QUEUED
                    and run.updated_at is not None
                    and run.updated_at <= queued_before
                )
                dead_worker = run.status is RunStatus.RUNNING and not run.lease_active(now)
                if not (stalled_queue or dead_worker):
                    return False  # re-checked inside the transaction: state moved on
                bumped = dataclasses.replace(
                    run, dispatch_generation=run.dispatch_generation + 1, updated_at=now
                )
                tx.runs.save(actor, bumped)
                tx.outbox.save(
                    actor,
                    OutboxEntry(
                        delivery_id=bumped.delivery_id,
                        student_id=actor.student_id,
                        run_id=run_id,
                        status=OutboxStatus.PENDING,
                        created_at=now,
                    ),
                )
                return True

            if await self._uow.transaction(body):
                requeued += 1
        return requeued
