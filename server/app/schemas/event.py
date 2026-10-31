"""Client-facing event projection (API.md §1.6, §4).

There is no event request model: clients cannot publish events. Payloads are typed per
event type so internal fields (outbox ids, model reasoning, tool args) can never leak.
"""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from app.domain.types.assessment import AssessmentStatus
from app.domain.types.event import EventType
from app.domain.types.run import RunKind
from app.schemas.common import ApiModel, CourseId, OpaqueId, SkillId, UtcDatetime


class EventPayload(ApiModel):
    pass


class SessionPayload(EventPayload):
    task_id: OpaqueId


class RunPayload(EventPayload):
    kind: RunKind


class RunFailedPayload(RunPayload):
    error_code: str
    retryable: bool


class AssessmentCompletedPayload(EventPayload):
    assessment_id: OpaqueId
    status: AssessmentStatus


class MasteryUpdatedPayload(EventPayload):
    skill_ids: list[SkillId] = Field(min_length=1)
    assessment_id: OpaqueId


class PrerequisitePayload(EventPayload):
    mapping_id: OpaqueId
    source_skill_id: SkillId
    target_skill_id: SkillId
    task_id: OpaqueId | None = None


class PlanUpdatedPayload(EventPayload):
    plan_id: OpaqueId
    changed_task_ids: list[OpaqueId] = Field(default_factory=list)


class CoursePayload(EventPayload):
    course_id: CourseId


PAYLOAD_TYPES: dict[EventType, type[EventPayload]] = {
    EventType.SESSION_STARTED: SessionPayload,
    EventType.SESSION_COMPLETED: SessionPayload,
    EventType.SESSION_ABANDONED: SessionPayload,
    EventType.RUN_QUEUED: RunPayload,
    EventType.RUN_STARTED: RunPayload,
    EventType.RUN_WAITING_INPUT: RunPayload,
    EventType.RUN_COMPLETED: RunPayload,
    EventType.RUN_FAILED: RunFailedPayload,
    EventType.RUN_CANCELLED: RunPayload,
    EventType.ASSESSMENT_COMPLETED: AssessmentCompletedPayload,
    EventType.MASTERY_UPDATED: MasteryUpdatedPayload,
    EventType.PREREQUISITE_SUSPECTED: PrerequisitePayload,
    EventType.PREREQUISITE_CONFIRMED: PrerequisitePayload,
    EventType.PREREQUISITE_UNSUPPORTED: PrerequisitePayload,
    EventType.PLAN_UPDATED: PlanUpdatedPayload,
    EventType.COURSE_ENROLLED: CoursePayload,
    EventType.COURSE_UNENROLLED: CoursePayload,
}


class Event(ApiModel):
    event_id: OpaqueId
    sequence: int = Field(ge=1)
    schema_version: int = Field(ge=1)
    student_id: OpaqueId
    session_id: OpaqueId | None
    run_id: OpaqueId | None
    type: EventType
    occurred_at: UtcDatetime
    causation_id: OpaqueId | None
    payload: dict[str, object]

    @model_validator(mode="after")
    def _payload_matches_type(self) -> Self:
        # Validates (and rejects unknown keys in) the payload for this event type.
        PAYLOAD_TYPES[self.type].model_validate(self.payload)
        return self

    def typed_payload(self) -> EventPayload:
        return PAYLOAD_TYPES[self.type].model_validate(self.payload)


class EventPage(ApiModel):
    events: list[Event]
    next_after: int = Field(ge=0)
    has_more: bool
