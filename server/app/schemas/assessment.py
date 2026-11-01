from __future__ import annotations

from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from app.domain.types.assessment import (
    INDEPENDENT_OBSERVATIONS,
    AssessmentStatus,
    EvidenceObservation,
    UncertaintyLevel,
)
from app.domain.types.student import MasteryLevel
from app.schemas.common import ApiModel, CourseId, OpaqueId, SkillId, UtcDatetime

EvidenceRef = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_\-]+:[a-z]+:\d+-\d+$")]


class RubricResult(ApiModel):
    criterion_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9\-]*$")]
    earned: int = Field(ge=0)
    possible: int = Field(ge=1)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    assessable: bool = True

    @model_validator(mode="after")
    def _earned_within_possible(self) -> Self:
        if self.earned > self.possible:
            raise ValueError("earned cannot exceed possible")
        if not self.assessable and self.earned:
            raise ValueError("a criterion that could not be assessed earns no points")
        return self


class HintUsage(ApiModel):
    server_hint_count: int = Field(ge=0)
    self_reported_help: bool = False


class SkillEvidence(ApiModel):
    skill_id: SkillId
    observation: EvidenceObservation


class Uncertainty(ApiModel):
    level: UncertaintyLevel
    reasons: list[Annotated[str, StringConstraints(max_length=64)]] = Field(default_factory=list)


class Provenance(ApiModel):
    model_version: str
    workflow_version: str
    tool_result_ids: list[OpaqueId] = Field(default_factory=list)


class Assessment(ApiModel):
    """Server-produced only. No request model accepts any of these fields."""

    assessment_id: OpaqueId
    submission_id: OpaqueId
    session_id: OpaqueId
    run_id: OpaqueId
    status: AssessmentStatus
    question_version: str
    rubric_version: str
    rubric_results: list[RubricResult]
    hint_usage: HintUsage
    skill_evidence: list[SkillEvidence]
    uncertainty: Uncertainty
    provenance: Provenance
    supersedes_assessment_id: OpaqueId | None = None
    question_id: OpaqueId | None = None
    rubric_id: str | None = None
    # Student-facing feedback; limited when status is insufficient_evidence.
    feedback: Annotated[str, StringConstraints(max_length=2000)] = ""
    created_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _integrity(self) -> Self:
        if self.status is AssessmentStatus.INSUFFICIENT_EVIDENCE and self.skill_evidence:
            raise ValueError("insufficient_evidence assessments carry no skill evidence")
        if self.hint_usage.server_hint_count > 0 and any(
            e.observation in INDEPENDENT_OBSERVATIONS for e in self.skill_evidence
        ):
            raise ValueError("hint-assisted work cannot be recorded as independent evidence")
        return self


class AssessmentList(ApiModel):
    assessments: list[Assessment]
    next_cursor: str | None


class MasteryState(ApiModel):
    """A projection of accepted assessments. Not a grade and not an exam prediction."""

    skill_id: SkillId
    course_id: CourseId
    level: MasteryLevel
    independent_evidence_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    coverage: int = Field(ge=0)
    uncertainty: UncertaintyLevel
    updated_at: UtcDatetime | None
    rule_version: str


class MasteryList(ApiModel):
    mastery: list[MasteryState]
    next_cursor: str | None
