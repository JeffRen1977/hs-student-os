"""Schemas for synthetic seed fixtures (`server/fixtures/`). Never real student data."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from app.domain.types.course import EnrollmentStatus
from app.domain.types.student import PredictionStatus
from app.schemas.common import ApiModel, CourseId, UtcDatetime
from app.schemas.student import Entitlements, Goals, PredictionEntry, Preferences, Profile

SyntheticStudentId = Annotated[str, StringConstraints(pattern=r"^stu_[a-z0-9_]+$")]
SYNTHETIC_EMAIL_DOMAIN = "example.test"
# RFC 2606 reserved domain: guaranteed never to belong to a real student.
SyntheticEmail = Annotated[str, StringConstraints(pattern=r"^[a-z0-9._\-]+@example\.test$")]


class EnrollmentFixture(ApiModel):
    course_id: CourseId
    status: EnrollmentStatus
    enrolled_at: UtcDatetime


class StudentFixture(ApiModel):
    synthetic: bool
    student_id: SyntheticStudentId
    email: SyntheticEmail
    profile: Profile
    goals: Goals
    preferences: Preferences
    enrollments: list[EnrollmentFixture] = Field(default_factory=list)
    prediction_summary: dict[CourseId, PredictionEntry] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _synthetic_only(self) -> Self:
        if not self.synthetic:
            raise ValueError("fixtures must be marked synthetic")
        for course, prediction in self.prediction_summary.items():
            if prediction.status is not PredictionStatus.UNAVAILABLE:
                raise ValueError(f"prediction for {course} must be unavailable")
        return self


class EntitlementFixture(ApiModel):
    synthetic: bool
    student_id: SyntheticStudentId
    entitlements: Entitlements

    @model_validator(mode="after")
    def _synthetic_only(self) -> Self:
        if not self.synthetic:
            raise ValueError("fixtures must be marked synthetic")
        return self
