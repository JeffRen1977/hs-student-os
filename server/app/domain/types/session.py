from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
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
    # Internal: agent skills pinned when the session opened, and completion inputs.
    agent_skills: Sequence[str] = ()
    has_accepted_assessment: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


def completion_for(
    status: SessionStatus, active_run_id: str | None, has_accepted_assessment: bool
) -> CompletionEligibility:
    """Server-side completion rule (API.md §2.5): open, idle, and an accepted assessment."""
    if status is not SessionStatus.OPEN:
        return CompletionEligibility(eligible=False, reason=CompletionBlocker.SESSION_CLOSED)
    if active_run_id is not None:
        return CompletionEligibility(eligible=False, reason=CompletionBlocker.RUN_IN_PROGRESS)
    if not has_accepted_assessment:
        return CompletionEligibility(
            eligible=False, reason=CompletionBlocker.ACCEPTED_ASSESSMENT_REQUIRED
        )
    return CompletionEligibility(eligible=True)
