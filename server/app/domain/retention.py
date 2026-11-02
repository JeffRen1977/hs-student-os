"""Event retention (Step 31.5; the purge floor read by the event feed since Step 19).

Events older than `retention_days` are deleted oldest-first, and
`eventState.oldestRetainedSequence` is raised in the same transaction, so a client whose
cursor points below the floor gets 410 (replay from a fresh snapshot) rather than a
silent gap. Only the event log is trimmed: assessments, mastery, sessions and plans are
the student's record and are kept. Cloud Scheduler runs this daily.
"""

from __future__ import annotations

from datetime import timedelta

from app.domain.ports.repositories import OperationsStore, Tx, UnitOfWork
from app.domain.ports.runtime import Clock
from app.domain.types.actor import ActorContext

RETENTION_SERVICE = "event-retention"
BATCH = 200  # events deleted per transaction (Firestore allows 500 writes)


class EventRetention:
    def __init__(
        self, uow: UnitOfWork, operations: OperationsStore, clock: Clock, *, retention_days: int
    ) -> None:
        self._uow = uow
        self._ops = operations
        self._clock = clock
        self._retention = timedelta(days=retention_days)

    async def purge(self, page_size: int = 100) -> int:
        cutoff = self._clock.now() - self._retention
        total = 0
        after: str | None = None
        while True:
            ids = await self._ops.student_ids(after=after, limit=page_size)
            for sid in ids:
                actor = ActorContext.for_service(RETENTION_SERVICE, sid)
                while True:

                    async def body(tx: Tx, actor: ActorContext = actor) -> int:
                        return await tx.events.purge_before(actor, cutoff, BATCH)

                    purged = await self._uow.transaction(body)
                    total += purged
                    if purged < BATCH:
                        break
            if len(ids) < page_size:
                return total
            after = ids[-1]
