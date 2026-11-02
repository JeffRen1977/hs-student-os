"""One entry point for queue deliveries: Run executions and consumer wakes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.domain.run_execution import ProcessResult, RunExecutionService
from app.domain.types.outbox import Delivery, OutboxKind
from app.workers.consumers.runner import ConsumerRunner


async def _no_refresh() -> None:
    return None


class DeliveryRouter:
    def __init__(
        self,
        runs: RunExecutionService,
        consumers: ConsumerRunner,
        refresh_content: Callable[[], Awaitable[None]] = _no_refresh,
    ) -> None:
        """`refresh_content`: reload course packages if this instance's copy is stale, so
        a Run never fails because another instance activated its package moments ago."""
        self._runs = runs
        self._consumers = consumers
        self._refresh_content = refresh_content

    async def process(self, delivery: Delivery) -> ProcessResult:
        await self._refresh_content()
        if delivery.kind is OutboxKind.CONSUMERS:
            return await self._consumers.process(delivery)
        return await self._runs.process(delivery)
