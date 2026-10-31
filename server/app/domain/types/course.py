from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.types.common import AgentType, Availability, StudyMode, TaskType


class EnrollmentStatus(StrEnum):
    ACTIVE = "active"
    UNENROLLED = "unenrolled"


class CatalogStatus(StrEnum):
    """Per-student catalog state derived from availability + entitlement + enrollment."""

    ENROLLED = "enrolled"
    AVAILABLE = "available"
    LOCKED = "locked"
    COMING_SOON = "coming_soon"


class CourseCategory(StrEnum):
    AP = "AP"
    SAT = "SAT"
    ADMISSIONS = "ADMISSIONS"


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseEnrollment:
    student_id: str
    course_id: str
    status: EnrollmentStatus
    enrolled_at: datetime
    unenrolled_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentConfig:
    """Student-facing agent summary. Never contains prompts, tool endpoints, or indexes."""

    agent_type: AgentType
    modes: Sequence[StudyMode]
    supported_task_types: Sequence[TaskType]
    description: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseCatalogEntry:
    course_id: str
    name: str
    description: str
    category: CourseCategory
    availability: Availability
    entitled: bool
    enrolled: bool
    agent: AgentConfig

    @property
    def can_enroll(self) -> bool:
        return self.availability is Availability.ACTIVE and self.entitled and not self.enrolled

    @property
    def status(self) -> CatalogStatus:
        if self.availability is not Availability.ACTIVE:
            return CatalogStatus.COMING_SOON
        if self.enrolled:
            return CatalogStatus.ENROLLED
        return CatalogStatus.AVAILABLE if self.entitled else CatalogStatus.LOCKED


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseDefinition:
    """A course as the domain sees it, built from a versioned SubjectPack manifest."""

    course_id: str
    name: str
    description: str
    category: CourseCategory
    availability: Availability
    pack_version: str
    workflow_version: str | None
    agent: AgentConfig
    skills: Sequence[str] = ()

    @property
    def is_active(self) -> bool:
        return self.availability is Availability.ACTIVE


@dataclass(frozen=True, slots=True, kw_only=True)
class QuestionInfo:
    question_id: str
    version: str
    course_id: str
