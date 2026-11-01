"""Model-usage counters for budgets (Step 16.3). Retries are charged like any other call."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class BudgetScope(StrEnum):
    RUN = "run"
    SESSION = "session"
    DAY = "day"  # per student per UTC day


@dataclass(frozen=True, slots=True, kw_only=True)
class Reservation:
    tokens: int
    reserved_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class UsageCounter:
    key: str  # e.g. "run-run_01", "session-sess_01", "day-2026-11-02"
    scope: BudgetScope
    used_tokens: int = 0
    # In-flight model calls. Expired reservations (a crashed worker) stop counting.
    reservations: Mapping[str, Reservation] = field(default_factory=dict)
    updated_at: datetime | None = None

    def reserved_tokens(self, now: datetime, ttl_seconds: int) -> int:
        return sum(
            r.tokens
            for r in self.reservations.values()
            if (now - r.reserved_at).total_seconds() < ttl_seconds
        )
