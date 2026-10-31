from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

from app.domain.types.common import AgentType, Availability, StudyMode, TaskType
from app.domain.types.course import CourseCategory, EnrollmentStatus
from app.schemas.common import ApiModel, CourseId, RequestModel, SemVer, SkillId, UtcDatetime
from app.schemas.session import Session
from app.schemas.student import MasteryEntry


class PackSummary(ApiModel):
    """`GET /api/packs/{courseId}` — capability summary, no internal tool/index details."""

    course_id: CourseId
    name: str
    version: SemVer
    availability: Availability
    supported_task_types: list[TaskType]
    supported_modes: list[StudyMode]


class CatalogEntry(ApiModel):
    course_id: CourseId
    name: str
    description: Annotated[str, StringConstraints(max_length=500)]
    category: CourseCategory
    availability: Availability
    entitled: bool
    enrolled: bool


class CatalogResponse(ApiModel):
    courses: list[CatalogEntry]


class EnrollRequest(RequestModel):
    course_id: CourseId


class UnenrollRequest(RequestModel):
    course_id: CourseId


class Enrollment(ApiModel):
    course_id: CourseId
    enrolled_at: UtcDatetime
    status: EnrollmentStatus


class AgentSummary(ApiModel):
    agent_type: AgentType
    modes: list[StudyMode]
    supported_task_types: list[TaskType]


class EnrolledCourse(ApiModel):
    course_id: CourseId
    name: str
    enrolled_at: UtcDatetime
    status: EnrollmentStatus
    agent: AgentSummary


class EnrolledCoursesResponse(ApiModel):
    enrollments: list[EnrolledCourse]


class CourseAgentView(ApiModel):
    """`GET /api/courses/{courseId}/agent` — never exposes prompts or tool endpoints."""

    course_id: CourseId
    agent_type: AgentType
    name: str
    modes: list[StudyMode]
    supported_task_types: list[TaskType]
    active_sessions: list[Session]
    mastery_summary: dict[SkillId, MasteryEntry]
