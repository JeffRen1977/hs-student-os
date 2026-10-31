"""In-process queue for local development and tests (Step 15.1).

Durability does not come from this queue: the outbox and the stalled-run scan re-create
any delivery it loses on restart. Delivery is at-least-once, like Cloud Tasks; only an
identical delivery that is still pending is collapsed.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable

from app.domain.run_execution import ProcessResult
from app.domain.types.outbox import Delivery


class LocalQueue:
    def __init__(self) -> None:
        self._pending: OrderedDict[str, Delivery] = OrderedDict()
        self.enqueued: list[str] = []  # every enqueue call, for diagnostics/tests

    async def enqueue(self, delivery: Delivery) -> None:
        self.enqueued.append(delivery.delivery_id)
        self._pending.setdefault(delivery.delivery_id, delivery)

    def pending(self) -> list[Delivery]:
        return list(self._pending.values())

    async def drain(self, handler: Callable[[Delivery], Awaitable[ProcessResult]]) -> int:
        """Deliver everything pending once. RETRY results stay queued for the next drain."""
        batch = list(self._pending.values())
        self._pending.clear()
        processed = 0
        for delivery in batch:
            if await handler(delivery) is ProcessResult.RETRY:
                self._pending.setdefault(delivery.delivery_id, delivery)
            else:
                processed += 1
        return processed
