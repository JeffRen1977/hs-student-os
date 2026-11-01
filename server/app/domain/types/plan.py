"""Weekly plans produced by the evidence-aware planner (Step 25)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

PLANNER_RULE_VERSION = "planner-rules-v1"
HORIZON_DAYS = 7


class PlanPriority(StrEnum):
    """Ranked high → low: deadlines > evidence gaps > practice."""

    DEADLINE = "deadline"
    EVIDENCE_GAP = "evidence_gap"
    PRACTICE = "practice"


PRIORITY_ORDER: Sequence[PlanPriority] = tuple(PlanPriority)


class Placement(StrEnum):
    FIXED = "fixed"  # in progress, completed, or student-locked: never moved
    KEPT = "kept"  # already on a good day
    MOVED = "moved"  # moved to the earliest day with room
    DEFERRED = "deferred"  # no room this week: pushed past the horizon
    OVER_BUDGET = "over_budget"  # a deadline forced it in beyond the daily budget


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanEntry:
    task_id: str
    course_id: str
    duration_min: int
    previous_date: date
    scheduled_date: date
    priority: PlanPriority | None  # None for fixed entries
    placement: Placement
    explanation: str
    source_event_ids: Sequence[str] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Plan:
    plan_id: str
    student_id: str
    run_id: str | None
    rule_version: str
    local_date: date  # "today" in the student's timezone when planned
    horizon_end: date
    weekly_minutes: int
    daily_minutes: int
    evidence_available: bool  # False → conservative plan (no evidence-gap ranking)
    entries: Sequence[PlanEntry]
    created_at: datetime

    @property
    def changed_task_ids(self) -> list[str]:
        return [e.task_id for e in self.entries if e.previous_date != e.scheduled_date]


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanState:
    """`students/{id}/planState/current`: guards one non-terminal PLANNING run."""

    active_run_id: str | None = None
    latest_plan_id: str | None = None
    version: int = 0
