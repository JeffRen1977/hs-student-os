"""Drives the consumers for one student from a consumer wake (Step 24.4).

Each consumer keeps an offset (`consumerState/{consumer}`) into the student's event log.
One transaction handles at most one subscribed event: it reads the offset, skips events
the consumer ignores, applies the next subscribed one (effect + receipt) and advances the
offset — all or nothing. Delivery is at least once:

- a crash before that commit leaves offset, receipt and effect unwritten → the retry
  handles the event again;
- a crash after it means the effect and receipt exist → a replay (or a reset offset)
  finds the receipt and does nothing.

When every consumer has caught up, the wake's outbox entry is marked completed; a wake
that stays dispatched too long is re-issued by `RecoveryService`.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Sequence

from app.domain.ports.repositories import Tx, UnitOfWork
from app.domain.ports.runtime import Clock
from app.domain.run_execution import ProcessResult
from app.domain.types.actor import ActorContext, Permission
from app.domain.types.consumer import ConsumerOffset
from app.domain.types.outbox import Delivery, OutboxKind, OutboxStatus
from app.workers.consumers.base import Consumer

logger = logging.getLogger(__name__)

CONSUMER_SERVICE = "event-consumers"
SCAN_BATCH = 50
MAX_STEPS_PER_WAKE = 500


class ConsumerRunner:
    def __init__(
        self,
        uow: UnitOfWork,
        consumers: Sequence[Consumer],
        clock: Clock,
        *,
        max_steps: int = MAX_STEPS_PER_WAKE,
    ) -> None:
        self._uow = uow
        self._consumers = list(consumers)
        self._clock = clock
        self._max_steps = max_steps

    async def process(self, delivery: Delivery) -> ProcessResult:
        if delivery.kind is not OutboxKind.CONSUMERS:  # pragma: no cover - router guards
            raise ValueError("not a consumer wake")
        actor = ActorContext.for_service(CONSUMER_SERVICE, delivery.student_id)
        actor.require(Permission.RUN_EXECUTE)
        for consumer in self._consumers:
            try:
                caught_up = await self.drain(actor, consumer)
            except Exception as exc:  # the offset was not advanced; retry the wake later
                logger.warning(
                    "consumer_failed",
                    extra={"consumer": consumer.name, "error": type(exc).__name__},
                )
                return ProcessResult.RETRY
            if not caught_up:
                return ProcessResult.RETRY
        await self._complete(actor, delivery.delivery_id)
        return ProcessResult.DONE

    async def drain(self, actor: ActorContext, consumer: Consumer) -> bool:
        """Handle every pending event for one consumer. False if the step budget ran out."""
        for _ in range(self._max_steps):
            if not await self._uow.transaction(lambda tx: self._step(tx, actor, consumer)):
                return True
        return False

    async def _step(self, tx: Tx, actor: ActorContext, consumer: Consumer) -> bool:
        offset = await tx.consumer_offsets.get(actor, consumer.name)
        after = offset.processed_sequence if offset else 0
        events = await tx.events.list_after(actor, after, SCAN_BATCH)
        if not events:
            return False
        now = self._clock.now()
        last = events[-1].sequence
        for event in events:
            if event.type in consumer.subscribes:
                await consumer.handle(tx, actor, event, now)
                last = event.sequence
                break
        tx.consumer_offsets.save(
            actor, ConsumerOffset(consumer=consumer.name, processed_sequence=last, updated_at=now)
        )
        return True

    async def _complete(self, actor: ActorContext, delivery_id: str) -> None:
        async def body(tx: Tx) -> None:
            entry = await tx.outbox.get(actor, delivery_id)
            if entry is not None and entry.status is not OutboxStatus.COMPLETED:
                tx.outbox.save(actor, dataclasses.replace(entry, status=OutboxStatus.COMPLETED))

        await self._uow.transaction(body)
