from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class SessionStatus(StrEnum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


SESSION_TRANSITIONS: Mapping[SessionStatus, frozenset[SessionStatus]] = {
    SessionStatus.OPEN: frozenset({SessionStatus.COMPLETED, SessionStatus.ABANDONED}),
    SessionStatus.COMPLETED: frozenset(),
    SessionStatus.ABANDONED: frozenset(),
}


class CompletionBlocker(StrEnum):
    ACCEPTED_ASSESSMENT_REQUIRED = "accepted_assessment_required"
    RUN_IN_PROGRESS = "run_in_progress"
    SESSION_CLOSED = "session_closed"


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextVersion:
    pack: str
    workflow: str


@dataclass(frozen=True, slots=True, kw_only=True)
class CompletionEligibility:
    eligible: bool
    reason: CompletionBlocker | None = None

    def __post_init__(self) -> None:
        if self.eligible == (self.reason is not None):
            raise ValueError("an eligible session has no blocker; an ineligible one needs one")


@dataclass(frozen=True, slots=True, kw_only=True)
class Session:
    session_id: str
    student_id: str
    task_id: str
    course_id: str
    status: SessionStatus
    active_run_id: str | None
    context_version: ContextVersion
    completion: CompletionEligibility
    version: int
