"""Scheduled planning scan (Step 28.1). Cloud Scheduler calls
`POST /internal/planning/schedule` every few minutes; locally the worker loop calls it.

The scan only finds candidates. Each student is decided in its own transaction by
`app.domain.planning_schedule.schedule_due_planning`, which re-checks the due time, so
duplicate or overlapping invocations are harmless and one student's failure does not stop
the others.
"""

from __future__ import annotations

import logging
from collections import Counter

from app.domain.planning_schedule import (
    PlanningSchedulePolicy,
    ScheduleOutcome,
    schedule_due_planning,
)
from app.domain.ports.repositories import OperationsStore, Tx, UnitOfWork
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.types.actor import ActorContext

logger = logging.getLogger(__name__)

SCHEDULER_SERVICE = "planning-scheduler"


class PlanningScheduler:
    def __init__(
        self,
        uow: UnitOfWork,
        operations: OperationsStore,
        clock: Clock,
        ids: IdFactory,
        policy: PlanningSchedulePolicy,
    ) -> None:
        self._uow = uow
        self._ops = operations
        self._clock = clock
        self._ids = ids
        self._policy = policy

    async def run_due(self, limit: int = 200) -> Counter[ScheduleOutcome]:
        now = self._clock.now()
        outcomes: Counter[ScheduleOutcome] = Counter()
        for student_id in await self._ops.due_plan_schedules(due_before=now, limit=limit):
            actor = ActorContext.for_service(SCHEDULER_SERVICE, student_id)

            async def body(tx: Tx, actor: ActorContext = actor) -> ScheduleOutcome:
                return await schedule_due_planning(
                    tx, actor, self._policy, now=self._clock.now(), ids=self._ids
                )

            try:
                outcomes[await self._uow.transaction(body)] += 1
            except Exception as exc:  # isolate students; the next scan retries
                logger.warning(
                    "scheduled_planning_failed",
                    extra={"studentId": student_id, "error": type(exc).__name__},
                )
        if outcomes:
            logger.info("scheduled_planning_scan", extra={k.value: v for k, v in outcomes.items()})
        return outcomes
