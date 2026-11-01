"""Outbox → queue dispatch (Step 15.4, BACKEND.md §5.2).

Two entry points share one path:
- `dispatch_one` right after a command commits (best effort, from the API process);
- `dispatch_pending` from a periodic scan that catches anything the first attempt missed.

Order is enqueue, then mark dispatched. A crash between the two re-enqueues the same
deterministic delivery id later; the worker treats that duplicate as a no-op.
"""

from __future__ import annotations

import dataclasses
import logging

from app.domain.ports.execution import JobQueue
from app.domain.ports.repositories import OperationsStore, Tx, UnitOfWork
from app.domain.ports.runtime import Clock
from app.domain.types.actor import ActorContext
from app.domain.types.outbox import Delivery, OutboxEntry, OutboxStatus

logger = logging.getLogger(__name__)

DISPATCHER_SERVICE = "outbox-dispatcher"


class OutboxDispatcher:
    def __init__(
        self, uow: UnitOfWork, operations: OperationsStore, queue: JobQueue, clock: Clock
    ) -> None:
        self._uow = uow
        self._ops = operations
        self._queue = queue
        self._clock = clock

    async def dispatch_one(self, student_id: str, delivery_id: str) -> bool:
        actor = ActorContext.for_service(DISPATCHER_SERVICE, student_id)

        async def load(tx: Tx) -> OutboxEntry | None:
            return await tx.outbox.get(actor, delivery_id)

        entry = await self._uow.transaction(load)
        if entry is None or entry.status is not OutboxStatus.PENDING:
            return False
        await self._queue.enqueue(
            Delivery(
                delivery_id=entry.delivery_id,
                student_id=student_id,
                run_id=entry.run_id,
                kind=entry.kind,
            )
        )

        async def mark(tx: Tx) -> bool:
            current = await tx.outbox.get(actor, delivery_id)
            if current is None or current.status is not OutboxStatus.PENDING:
                return False
            tx.outbox.save(
                actor,
                dataclasses.replace(
                    current, status=OutboxStatus.DISPATCHED, dispatched_at=self._clock.now()
                ),
            )
            return True

        return await self._uow.transaction(mark)

    async def dispatch_pending(self, limit: int = 100) -> int:
        dispatched = 0
        for entry in await self._ops.pending_outbox(limit):
            try:
                if await self.dispatch_one(entry.student_id, entry.delivery_id):
                    dispatched += 1
            except Exception as exc:  # keep scanning; the entry stays pending
                logger.warning(
                    "outbox_dispatch_failed",
                    extra={"deliveryId": entry.delivery_id, "error": type(exc).__name__},
                )
        return dispatched

    async def dispatch_after_commit(self, student_id: str, delivery_id: str) -> None:
        """Best-effort immediate delivery. Failure is logged; the scan will retry."""
        try:
            await self.dispatch_one(student_id, delivery_id)
        except Exception as exc:
            logger.warning(
                "immediate_dispatch_failed",
                extra={"deliveryId": delivery_id, "error": type(exc).__name__},
            )
