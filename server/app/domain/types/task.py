from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from app.domain.types.common import AgentType, StudyMode, TaskType


class TaskStatus(StrEnum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"


class TaskReasonCode(StrEnum):
    INITIAL_PRACTICE = "INITIAL_PRACTICE"
    STUDENT_SCHEDULED = "STUDENT_SCHEDULED"
    REVIEW_DUE = "REVIEW_DUE"


TASK_TRANSITIONS: Mapping[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PLANNED: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.SKIPPED}),
    TaskStatus.IN_PROGRESS: frozenset({TaskStatus.COMPLETED, TaskStatus.PLANNED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.SKIPPED: frozenset(),
}
"""IN_PROGRESS → PLANNED happens only when the open Session is abandoned (API.md §2.5)."""


class SkipReason(StrEnum):
    NO_TIME = "no_time"
    ALREADY_KNOW = "already_know"
    NOT_RELEVANT = "not_relevant"
    OTHER = "other"


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskReason:
    code: TaskReasonCode
    source_event_ids: Sequence[str] = ()
    # Server-written, student-facing sentence: why this task exists (never model output).
    explanation: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class Task:
    task_id: str
    student_id: str
    agent: AgentType
    course_id: str
    task_type: TaskType
    mode: StudyMode
    title: str
    duration_min: int
    scheduled_date: date
    status: TaskStatus
    version: int
    reason: TaskReason
    student_locked: bool = False
    open_session_id: str | None = None  # internal guard: at most one OPEN Session per Task
    question_id: str | None = None  # content the task practices; pinned on its Session
    due_date: date | None = None  # a real deadline (planner priority 1), if any
    skip_reason: SkipReason | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class TaskPatch:
    """The only Task fields a student may change (API.md §2.1)."""

    scheduled_date: date | None = None
    student_locked: bool | None = None
    skip: bool = False
    skip_reason: SkipReason | None = None
