from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class EventType(StrEnum):
    SESSION_STARTED = "session.started"
    SESSION_COMPLETED = "session.completed"
    SESSION_ABANDONED = "session.abandoned"
    RUN_QUEUED = "run.queued"
    RUN_STARTED = "run.started"
    RUN_WAITING_INPUT = "run.waiting_input"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    ASSESSMENT_COMPLETED = "assessment.completed"
    MASTERY_UPDATED = "mastery.updated"
    PREREQUISITE_SUSPECTED = "prerequisite.suspected"
    PREREQUISITE_CONFIRMED = "prerequisite.confirmed"
    PREREQUISITE_UNSUPPORTED = "prerequisite.unsupported"
    PLAN_UPDATED = "plan.updated"
    COURSE_ENROLLED = "course.enrolled"
    COURSE_UNENROLLED = "course.unenrolled"


CURRENT_EVENT_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class DomainEvent:
    """Server-generated, assigned a per-student monotonic sequence inside a transaction.

    `payload` here is the internal payload; clients only ever see the filtered projection
    defined in `app.schemas.event`.
    """

    event_id: str
    sequence: int
    schema_version: int
    student_id: str
    type: EventType
    occurred_at: datetime
    causation_id: str | None
    session_id: str | None = None
    run_id: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("event sequences start at 1")
