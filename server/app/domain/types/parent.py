"""Parent links and summaries (Step 36).

A parent is a separate identity (`parents/{uid}`), never a student. A student grants a
parent access by creating an invite; the parent redeems its one-time code; the student can
revoke the link at any time. Every parent read re-checks, in the same transaction, that the
link is active and grants the scope being used. The only scope is `summary:read`: course
progress and the week's plan, never chats, answers, feedback, essays or admissions data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from app.domain.types.student import MasteryLevel

INVITE_TTL_DAYS = 7


class ParentLinkStatus(StrEnum):
    PENDING = "pending"  # invite created by the student, not yet redeemed
    ACTIVE = "active"
    REVOKED = "revoked"  # by the student; final
    EXPIRED = "expired"  # invite not redeemed in time; final


@dataclass(frozen=True, slots=True, kw_only=True)
class ParentLink:
    link_id: str
    student_id: str
    status: ParentLinkStatus
    scopes: Sequence[str]
    invite_code_hash: str
    invite_expires_at: datetime
    created_at: datetime
    parent_uid: str | None = None
    parent_display_name: str | None = None
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None
    version: int = 1

    def is_active_for(self, parent_uid: str) -> bool:
        return self.status is ParentLinkStatus.ACTIVE and self.parent_uid == parent_uid


@dataclass(frozen=True, slots=True, kw_only=True)
class ParentInvite:
    """`parentInvites/{codeHash}` → which student's link a code redeems. Holds no student
    data beyond the id needed to find the link."""

    code_hash: str
    student_id: str
    link_id: str
    expires_at: datetime
    redeemed_by: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ParentChild:
    """`parents/{uid}/children/{studentId}`: the parent's index of links. Never trusted on
    its own: each read re-checks the student-side link."""

    student_id: str
    link_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillProgress:
    skill_id: str
    level: MasteryLevel
    independent_evidence_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseProgress:
    course_id: str
    name: str
    skills: Sequence[SkillProgress]
    prediction_status: str  # always "unavailable" until calibrated (Step 37)


@dataclass(frozen=True, slots=True, kw_only=True)
class UpcomingTask:
    course_id: str
    title: str
    scheduled_date: date
    duration_min: int


@dataclass(frozen=True, slots=True, kw_only=True)
class WeekSummary:
    start: date
    end: date
    planned: int
    completed: int
    skipped: int
    upcoming: Sequence[UpcomingTask]


@dataclass(frozen=True, slots=True, kw_only=True)
class ParentSummary:
    student_id: str
    display_name: str
    grade: int
    courses: Sequence[CourseProgress]
    week: WeekSummary
    generated_at: datetime
