"""Parent links and summaries (Step 36, API.md §6.4)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.schemas.common import ApiModel, CourseId, OpaqueId, RequestModel, UtcDatetime

Scope = Literal["summary:read"]


class CreateParentLinkRequest(RequestModel):
    scopes: list[Scope] = Field(min_length=1, max_length=1)


class ParentLinkView(ApiModel):
    link_id: OpaqueId
    status: Literal["pending", "active", "revoked", "expired"]
    scopes: list[Scope]
    created_at: UtcDatetime
    invite_expires_at: UtcDatetime
    parent_display_name: str | None = None
    accepted_at: UtcDatetime | None = None
    revoked_at: UtcDatetime | None = None


class CreatedParentLink(ParentLinkView):
    # Shown once, to the student. Null on an idempotent replay: only its hash is stored.
    invite_code: str | None


class ParentLinkList(ApiModel):
    links: list[ParentLinkView]


class AcceptParentLinkRequest(RequestModel):
    invite_code: Annotated[str, StringConstraints(min_length=4, max_length=64)]


class LinkedStudent(ApiModel):
    student_id: OpaqueId
    display_name: str
    linked_at: UtcDatetime


class LinkedStudentList(ApiModel):
    students: list[LinkedStudent]


class SkillProgressView(ApiModel):
    skill_id: str
    level: Literal["insufficient_evidence", "emerging", "developing", "proficient"]
    independent_evidence_count: int


class CourseProgressView(ApiModel):
    course_id: CourseId
    name: str
    skills: list[SkillProgressView]
    prediction: Literal["unavailable"]


class UpcomingTaskView(ApiModel):
    course_id: CourseId
    title: str
    scheduled_date: str
    duration_min: int


class WeekView(ApiModel):
    start: str
    end: str
    planned: int
    completed: int
    skipped: int
    upcoming: list[UpcomingTaskView]


class ParentSummaryView(ApiModel):
    """`summary:read`. Built field by field: no messages, answers, feedback, essays,
    admissions facts, entitlements or event payloads."""

    student_id: OpaqueId
    display_name: str
    grade: int
    courses: list[CourseProgressView]
    week: WeekView
    generated_at: UtcDatetime
