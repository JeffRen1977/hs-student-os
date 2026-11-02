"""Operational alert checks (Step 31.3).

Cloud Scheduler calls `POST /internal/ops/check` every 5 minutes. Each check reads only
operational metadata (outbox entries, run status and error codes), never student content.
A firing alert is logged at ERROR as `alert_firing` (the Cloud Monitoring alert policy in
`deploy/monitoring/` fires on it) and recorded as an `ops.alert` metric.

- `outbox_backlog`: pending outbox entries older than `outbox_age` — the dispatcher or the
  queue is not keeping up (or is down).
- `worker_failures`: runs that ended FAILED in the last hour.
- `budget_overruns`: runs that failed with BUDGET_EXCEEDED in the last hour.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from app.domain.errors import ErrorCode
from app.domain.ports.metrics import Metrics
from app.domain.ports.repositories import OperationsStore
from app.domain.ports.runtime import Clock

logger = logging.getLogger(__name__)

WINDOW = timedelta(hours=1)


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertThresholds:
    outbox_backlog: int = 50
    outbox_age_seconds: int = 300
    failed_runs_per_hour: int = 10
    budget_overruns_per_hour: int = 5


@dataclass(frozen=True, slots=True, kw_only=True)
class AlertState:
    alert: str
    firing: bool
    observed: int
    threshold: int


class OpsMonitor:
    def __init__(
        self,
        operations: OperationsStore,
        clock: Clock,
        metrics: Metrics,
        thresholds: AlertThresholds,
    ) -> None:
        self._ops = operations
        self._clock = clock
        self._metrics = metrics
        self._t = thresholds

    async def check(self) -> list[AlertState]:
        now = self._clock.now()
        t = self._t
        scan_limit = max(t.outbox_backlog, t.failed_runs_per_hour, t.budget_overruns_per_hour) * 4
        old_before = now - timedelta(seconds=t.outbox_age_seconds)
        pending = await self._ops.pending_outbox(scan_limit)
        backlog = sum(1 for e in pending if e.created_at <= old_before)
        failed = await self._ops.failed_runs_since(since=now - WINDOW, limit=scan_limit)
        budget = sum(
            1 for r in failed if r.error is not None and r.error.code == ErrorCode.BUDGET_EXCEEDED
        )
        states = [
            AlertState(
                alert="outbox_backlog",
                firing=backlog >= t.outbox_backlog,
                observed=backlog,
                threshold=t.outbox_backlog,
            ),
            AlertState(
                alert="worker_failures",
                firing=len(failed) >= t.failed_runs_per_hour,
                observed=len(failed),
                threshold=t.failed_runs_per_hour,
            ),
            AlertState(
                alert="budget_overruns",
                firing=budget >= t.budget_overruns_per_hour,
                observed=budget,
                threshold=t.budget_overruns_per_hour,
            ),
        ]
        self._metrics.observe("outbox.backlog", backlog)
        self._metrics.observe("runs.failed_last_hour", len(failed))
        for s in states:
            if s.firing:
                self._metrics.count("ops.alert", alert=s.alert)
                logger.error(
                    "alert_firing",
                    extra={"alert": s.alert, "observed": s.observed, "threshold": s.threshold},
                )
        return states
