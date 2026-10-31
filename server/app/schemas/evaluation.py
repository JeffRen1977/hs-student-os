"""Schemas for the learning-evaluation baseline (`server/content/evaluation/`).

These describe *expected* outcomes reviewed by humans. They are a content gate, not
evidence that any model meets them.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from app.domain.types.assessment import AssessmentStatus, EvidenceObservation, UncertaintyLevel
from app.domain.types.event import EventType
from app.schemas.common import ApiModel, OpaqueId, SkillId
from app.schemas.content import ContentSource, Review, RubricRef, Slug

NonEmpty = Annotated[str, StringConstraints(min_length=1)]

PREREQUISITE_EVENTS = frozenset(
    {
        EventType.PREREQUISITE_SUSPECTED,
        EventType.PREREQUISITE_CONFIRMED,
        EventType.PREREQUISITE_UNSUPPORTED,
    }
)


class QuestionRef(ApiModel):
    question_id: OpaqueId
    version: NonEmpty


class EvaluationProvenance(ApiModel):
    synthetic: Literal[True]
    source: ContentSource
    notes: str | None = None


class SessionContext(ApiModel):
    server_hint_count: int = Field(ge=0)
    hint_summaries: list[NonEmpty] = Field(default_factory=list)

    @model_validator(mode="after")
    def _summaries_match_count(self) -> Self:
        if len(self.hint_summaries) != self.server_hint_count:
            raise ValueError("one hint summary per server hint")
        return self


class StudentAnswer(ApiModel):
    text: NonEmpty


class ExpectedCriterion(ApiModel):
    criterion_id: Slug
    earned: int = Field(ge=0)


class ExpectedEvidence(ApiModel):
    skill_id: SkillId
    observation: EvidenceObservation


class ExpectedAssessment(ApiModel):
    status: AssessmentStatus
    rubric_results: list[ExpectedCriterion] = Field(min_length=1)
    skill_evidence: list[ExpectedEvidence]
    uncertainty_level: UncertaintyLevel
    feedback_focus: list[NonEmpty] = Field(min_length=1)

    @model_validator(mode="after")
    def _status_rules(self) -> Self:
        if self.status is AssessmentStatus.INSUFFICIENT_EVIDENCE and self.skill_evidence:
            raise ValueError("insufficient_evidence must not produce skill evidence")
        return self


AssessmentCaseCategory = Literal[
    "correct", "incorrect", "partial", "assisted", "ambiguous", "insufficient_work"
]


class AssessmentEvaluationCase(ApiModel):
    case_id: Slug
    version: NonEmpty
    category: AssessmentCaseCategory
    question_ref: QuestionRef
    rubric_ref: RubricRef
    student_answer: StudentAnswer
    session_context: SessionContext
    expected: ExpectedAssessment
    rationale: NonEmpty
    provenance: EvaluationProvenance
    review: Review


class PrerequisiteObservation(ApiModel):
    question_ref: QuestionRef
    student_answer: StudentAnswer
    assessment_status: AssessmentStatus
    server_hint_count: int = Field(ge=0)
    error_description: NonEmpty
    skill_evidence: list[ExpectedEvidence]


class ExpectedPrerequisiteEvent(ApiModel):
    type: EventType
    mapping_id: OpaqueId

    @model_validator(mode="after")
    def _prerequisite_only(self) -> Self:
        if self.type not in PREREQUISITE_EVENTS:
            raise ValueError("only prerequisite.* events belong in prerequisite expectations")
        return self


class ExpectedPrerequisiteOutcome(ApiModel):
    events: list[ExpectedPrerequisiteEvent]
    forbidden_events: list[ExpectedPrerequisiteEvent] = Field(min_length=1)

    @model_validator(mode="after")
    def _confirmation_needs_diagnostic(self) -> Self:
        # Assessments alone may at most *suspect* a SAT weakness (CLAUDE.md §6.2).
        if any(e.type is not EventType.PREREQUISITE_SUSPECTED for e in self.events):
            raise ValueError("calculus evidence alone can only produce prerequisite.suspected")
        return self


class PrerequisiteEvaluationCase(ApiModel):
    case_id: Slug
    version: NonEmpty
    category: Literal["counterexample", "supporting"]
    mapping_set_id: Slug
    mapping_set_version: NonEmpty
    observations: list[PrerequisiteObservation] = Field(min_length=1)
    expected: ExpectedPrerequisiteOutcome
    rationale: NonEmpty
    provenance: EvaluationProvenance
    review: Review

    @model_validator(mode="after")
    def _category_matches_expectation(self) -> Self:
        if self.category == "counterexample" and self.expected.events:
            raise ValueError("counterexamples expect no prerequisite events")
        if self.category == "supporting" and not self.expected.events:
            raise ValueError("supporting cases expect a prerequisite.suspected event")
        return self


class EvaluationDimension(ApiModel):
    dimension_id: Slug
    name: NonEmpty
    definition: NonEmpty
    measurement: NonEmpty
    direction: Literal["higher_is_better", "lower_is_better"]
    # Thresholds are set by a content reviewer, never inferred from examples.
    threshold: float | None = None
    threshold_set_by: NonEmpty | None = None

    @model_validator(mode="after")
    def _threshold_has_owner(self) -> Self:
        if (self.threshold is None) != (self.threshold_set_by is None):
            raise ValueError("a threshold must name the reviewer who set it")
        return self


class EvaluationDimensions(ApiModel):
    version: NonEmpty
    dimensions: list[EvaluationDimension] = Field(min_length=1)
