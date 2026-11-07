"""Course package contract v1 (doc/COURSE_PACKAGE.md) and the authoring/review API.

A package is one JSON document that fully describes a course as data: manifest, skill
taxonomy, rubrics, question bank, optional reference materials, starter tasks and an
evaluation set. It contains no code. Abilities and tools are chosen from the platform
catalog; anything else is rejected by the validator (`app.registries.package_validator`).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from app.domain.types.common import AgentType, StudyMode, TaskType
from app.domain.types.course import CourseCategory
from app.schemas.common import (
    ApiModel,
    CourseId,
    OpaqueId,
    RequestModel,
    SemVer,
    SkillId,
    UtcDatetime,
)
from app.schemas.content import Material, Question, Rubric, SkillDefinition, Slug

PACKAGE_SCHEMA_VERSION = "course-package/v1"
MAX_PACKAGE_BYTES = 900_000  # one Firestore document; larger packages move to Storage later

NonEmpty = Annotated[str, StringConstraints(min_length=1)]
Note = Annotated[str, StringConstraints(max_length=2000)]


class Publisher(ApiModel):
    """Display name of the author organization. Ownership itself comes from the
    authenticated author's organization, never from this field."""

    name: Annotated[str, StringConstraints(min_length=1, max_length=120)]


class PackageManifest(ApiModel):
    course_id: CourseId
    version: SemVer
    name: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    description: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    category: CourseCategory  # catalog label only; never grants access
    agent_type: AgentType
    supported_task_types: list[TaskType] = Field(min_length=1)
    supported_modes: list[StudyMode] = Field(min_length=1)
    abilities: list[Slug] = Field(min_length=1)  # from the platform ability catalog
    tools: list[Slug] = Field(default_factory=list)  # from the platform tool catalog
    model_tier: Literal["fast", "balanced", "strong"]
    context_budget_tokens: int = Field(default=8000, ge=1000, le=200_000)
    workflow_version: Slug
    publisher: Publisher
    license: Annotated[str, StringConstraints(min_length=1, max_length=300)]


class StarterTask(ApiModel):
    """A task created for a student when they first enroll (no tasks yet in the course)."""

    question_id: OpaqueId
    task_type: TaskType
    mode: StudyMode
    title: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    duration_min: int = Field(ge=5, le=120)


class EvaluationCase(ApiModel):
    """An annotated answer the course must grade as expected before review.

    `expectedEarned` maps every rubric criterion of the question to the points the answer
    should earn. Cases on key-scored questions are run by the platform at upload; cases
    that need model grading are attested by the reviewer.
    """

    case_id: Slug
    question_id: OpaqueId
    answer_text: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    expected_status: Literal["accepted", "insufficient_evidence"] = "accepted"
    expected_earned: dict[Slug, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _accepted_needs_points(self) -> Self:
        if self.expected_status == "accepted" and not self.expected_earned:
            raise ValueError("accepted cases need expectedEarned for every criterion")
        return self


class CoursePackage(ApiModel):
    schema_version: Literal["course-package/v1"]
    manifest: PackageManifest
    system_prompt: Annotated[str, StringConstraints(min_length=1, max_length=8000)]
    skills: list[SkillDefinition] = Field(min_length=1, max_length=200)
    rubrics: list[Rubric] = Field(min_length=1, max_length=500)
    questions: list[Question] = Field(min_length=1, max_length=500)
    materials: list[Material] = Field(default_factory=list, max_length=200)
    starter_tasks: list[StarterTask] = Field(default_factory=list, max_length=20)
    # Offered in order after the starter tasks by the practice top-up rule (BACKEND.md §9).
    practice_sequence: list[StarterTask] = Field(default_factory=list, max_length=200)
    evaluation_set: list[EvaluationCase] = Field(min_length=1, max_length=200)


# ---- Authoring and review API -------------------------------------------------------------


class PackageUploadRequest(RequestModel):
    """`POST /api/authoring/packages`. The package is validated by the server, so it is
    accepted here as an object and parsed against `CoursePackage` with full error paths."""

    package: dict[str, Any]


class ReviewApproveRequest(RequestModel):
    notes: Note = ""
    license_attested: bool
    model_evaluation_attested: bool = False


class ReviewRejectRequest(RequestModel):
    notes: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class RetireRequest(RequestModel):
    notes: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class EmptyCommand(RequestModel):
    pass


class PackageIssueView(ApiModel):
    path: str
    code: str
    message: str


class EvaluationView(ApiModel):
    auto_cases: int
    auto_passed: int
    model_cases: int
    failures: list[str]


class ValidationReportView(ApiModel):
    valid: bool
    validator_version: str
    errors: list[PackageIssueView]
    evaluation: EvaluationView


class ReviewDecisionView(ApiModel):
    reviewer_id: str
    decision: Literal["approved", "rejected"]
    decided_at: UtcDatetime
    notes: str
    license_attested: bool
    model_evaluation_attested: bool


class StatusChangeView(ApiModel):
    from_status: str | None
    to_status: str
    actor_id: str
    at: UtcDatetime
    notes: str


class PackageVersionView(ApiModel):
    course_id: CourseId
    version: SemVer
    title: str
    status: Literal["draft", "submitted", "approved", "active", "superseded", "rejected", "retired"]
    org_id: str
    content_hash: str
    uploaded_by: str
    created_at: UtcDatetime
    updated_at: UtcDatetime
    report: ValidationReportView
    review: ReviewDecisionView | None
    history: list[StatusChangeView]
    # Present on single-version reads (author of the owning org, or a reviewer).
    package: dict[str, Any] | None = None


class PackageVersionList(ApiModel):
    versions: list[PackageVersionView]


# ---- Author portal: student-view preview and aggregate metrics (Step 34) -------------------


class PreviewChoice(ApiModel):
    key: str
    text: str


class PreviewItem(ApiModel):
    item_id: str
    prompt: str
    choices: list[PreviewChoice]  # never the answer key


class PreviewSource(ApiModel):
    material_id: str
    title: str
    text: str


class PreviewQuestion(ApiModel):
    question_id: str
    version: str
    topic: str
    prompt: str
    items: list[PreviewItem] | None = None
    sources: list[PreviewSource] | None = None


class PreviewSkill(ApiModel):
    skill_id: str
    name: str


class PreviewStarterTask(ApiModel):
    question_id: str
    title: str
    task_type: TaskType
    mode: StudyMode
    duration_min: int


class PackagePreview(ApiModel):
    """What a student would see of this version: no rubrics, expected answers, answer
    keys, evaluation set or system prompt. Available for valid packages only."""

    course_id: CourseId
    version: SemVer
    name: str
    description: str
    skills: list[PreviewSkill]
    starter_tasks: list[PreviewStarterTask]
    practice_sequence: list[PreviewStarterTask] = Field(default_factory=list)
    questions: list[PreviewQuestion]


class CriterionMetricView(ApiModel):
    rubric_id: str
    criterion_id: str
    count: int  # accepted assessments that scored this criterion
    average_earned: float
    max_points: float  # average possible per assessment


class CourseMetricsView(ApiModel):
    """Aggregates only. Below `minimumCohort` distinct students everything but the
    threshold is withheld (`suppressed: true`)."""

    course_id: CourseId
    suppressed: bool
    minimum_cohort: int
    students: int | None = None
    assessments: int | None = None
    by_status: dict[str, int] | None = None
    criteria: list[CriterionMetricView] | None = None
    updated_at: UtcDatetime | None = None


__all__ = [
    "MAX_PACKAGE_BYTES",
    "PACKAGE_SCHEMA_VERSION",
    "CoursePackage",
    "EvaluationCase",
    "Material",
    "PackageManifest",
    "Question",
    "Rubric",
    "SkillDefinition",
    "SkillId",
    "StarterTask",
]
