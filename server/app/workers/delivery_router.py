"""One entry point for queue deliveries: Run executions and consumer wakes."""

from __future__ import annotations

from app.domain.run_execution import ProcessResult, RunExecutionService
from app.domain.types.outbox import Delivery, OutboxKind
from app.workers.consumers.runner import ConsumerRunner


class DeliveryRouter:
    def __init__(self, runs: RunExecutionService, consumers: ConsumerRunner) -> None:
        self._runs = runs
        self._consumers = consumers

    async def process(self, delivery: Delivery) -> ProcessResult:
        if delivery.kind is OutboxKind.CONSUMERS:
            return await self._consumers.process(delivery)
        return await self._runs.process(delivery)
