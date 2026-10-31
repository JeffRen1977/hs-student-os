"""Local-only background loop: recovery scan → outbox dispatch → drain queue → worker.

Started by the API process when `HSOS_QUEUE_PROVIDER=local` and
`HSOS_LOCAL_WORKER_ENABLED=true`. Deployed environments use Cloud Tasks + the worker
service instead (and refuse the local queue at startup).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from app.adapters.queue.local_queue import LocalQueue
from app.domain.recovery import RecoveryService
from app.domain.run_execution import RunExecutionService
from app.workers.outbox_dispatcher import OutboxDispatcher

logger = logging.getLogger(__name__)


class LocalWorkerLoop:
    def __init__(
        self,
        *,
        queue: LocalQueue,
        dispatcher: OutboxDispatcher,
        recovery: RecoveryService,
        execution: RunExecutionService,
        poll_seconds: float,
    ) -> None:
        self._queue = queue
        self._dispatcher = dispatcher
        self._recovery = recovery
        self._execution = execution
        self._poll = poll_seconds
        self._task: asyncio.Task[None] | None = None

    async def tick(self) -> int:
        await self._recovery.requeue_stalled()
        await self._dispatcher.dispatch_pending()
        return await self._queue.drain(self._execution.process)

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:  # keep the dev loop alive; state is durable
                logger.warning("local_worker_tick_failed", extra={"error": type(exc).__name__})
            await asyncio.sleep(self._poll)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="local-worker-loop")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
