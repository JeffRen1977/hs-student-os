"""Schemas for synthetic seed fixtures (`server/fixtures/`). Never real student data."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from app.domain.types.course import EnrollmentStatus
from app.domain.types.student import PredictionStatus
from app.schemas.common import ApiModel, CourseId, UtcDatetime
from app.schemas.student import Entitlements, Goals, PredictionEntry, Preferences, Profile
from app.schemas.task import Task

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


class TaskFixture(ApiModel):
    synthetic: bool
    student_id: SyntheticStudentId
    tasks: list[Task] = Field(default_factory=list)

    @model_validator(mode="after")
    def _synthetic_and_owned(self) -> Self:
        if not self.synthetic:
            raise ValueError("fixtures must be marked synthetic")
        if any(t.student_id != self.student_id for t in self.tasks):
            raise ValueError("every task must belong to the fixture student")
        return self


class PlatformMemberFixture(ApiModel):
    uid: Annotated[str, StringConstraints(pattern=r"^(author|reviewer)_[a-z0-9_]+$")]
    role: Literal["author", "platform_reviewer"]
    org_id: Annotated[str, StringConstraints(pattern=r"^org_[a-z0-9_]+$")] | None
    email: SyntheticEmail
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=80)]

    @model_validator(mode="after")
    def _authors_have_an_org(self) -> Self:
        if (self.role == "author") != (self.org_id is not None):
            raise ValueError("authors belong to one organization; reviewers to none")
        return self


class SeedPackageFixture(ApiModel):
    """A package under `content/authored/{path}/package.json` that local seeding installs.

    `active`: installed as already approved — a local development convenience whose audit
    trail says it is a seed, not a review. `submitted`: uploaded and submitted, waiting in
    the platform review queue like any author submission. The review gate itself is
    exercised through the API (tests/contract/test_package_review.py)."""

    path: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]+$")]
    org_id: Annotated[str, StringConstraints(pattern=r"^org_[a-z0-9_]+$")]
    uploaded_by: str
    status: Literal["active", "submitted"] = "active"


class ParentFixture(ApiModel):
    """A synthetic parent account (Step 36). Links to students are created by students."""

    uid: Annotated[str, StringConstraints(pattern=r"^parent_[a-z0-9_]+$")]
    email: SyntheticEmail
    display_name: Annotated[str, StringConstraints(min_length=1, max_length=80)]


class PlatformFixture(ApiModel):
    synthetic: bool
    members: list[PlatformMemberFixture]
    parents: list[ParentFixture] = Field(default_factory=list)
    seed_packages: list[SeedPackageFixture] = Field(default_factory=list)

    @model_validator(mode="after")
    def _synthetic_only(self) -> Self:
        if not self.synthetic:
            raise ValueError("fixtures must be marked synthetic")
        return self
