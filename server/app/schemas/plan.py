"""Plans from the evidence-aware planner (Step 25). Read-only: replans are commands."""

from __future__ import annotations

from pydantic import Field

from app.domain.types.plan import Placement, PlanPriority
from app.schemas.common import ApiModel, CourseId, LocalDate, OpaqueId, UtcDatetime


class PlanEntry(ApiModel):
    task_id: OpaqueId
    course_id: CourseId
    duration_min: int = Field(ge=1)
    previous_date: LocalDate
    scheduled_date: LocalDate
    priority: PlanPriority | None  # null for fixed entries
    placement: Placement
    explanation: str
    source_event_ids: list[OpaqueId] = Field(default_factory=list)


class Plan(ApiModel):
    plan_id: OpaqueId
    run_id: OpaqueId | None
    rule_version: str
    local_date: LocalDate
    horizon_end: LocalDate
    weekly_minutes: int = Field(ge=0)
    daily_minutes: int = Field(ge=1)
    evidence_available: bool
    entries: list[PlanEntry]
    created_at: UtcDatetime
