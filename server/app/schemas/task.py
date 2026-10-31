from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from app.domain.types.common import AgentType, StudyMode, TaskType
from app.domain.types.task import TaskReasonCode, TaskStatus
from app.schemas.common import ApiModel, CourseId, LocalDate, OpaqueId, RequestModel


class TaskReason(ApiModel):
    code: TaskReasonCode
    source_event_ids: list[OpaqueId] = Field(default_factory=list, max_length=50)


class Task(ApiModel):
    task_id: OpaqueId
    student_id: OpaqueId
    agent: AgentType
    course_id: CourseId
    task_type: TaskType
    mode: StudyMode
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    duration_min: int = Field(ge=1, le=240)
    scheduled_date: LocalDate
    status: TaskStatus
    version: int = Field(ge=1)
    reason: TaskReason
    student_locked: bool = False


class TaskList(ApiModel):
    tasks: list[Task]
    next_cursor: str | None


class TaskPatchRequest(RequestModel):
    """`PATCH /api/tasks/{taskId}` + If-Match. Students may only reschedule, lock, or skip.

    Completion is decided by the Session completion rules, never by a client PATCH.
    """

    scheduled_date: LocalDate | None = None
    student_locked: bool | None = None
    status: Literal[TaskStatus.SKIPPED] | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("patch must change at least one field")
        return self
