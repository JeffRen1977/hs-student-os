from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AssessmentStatus(StrEnum):
    ACCEPTED = "accepted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class EvidenceObservation(StrEnum):
    CORRECT_INDEPENDENT = "correct_independent"
    CORRECT_WITH_HINT = "correct_with_hint"
    PARTIALLY_CORRECT = "partially_correct"
    INCORRECT = "incorrect"


INDEPENDENT_OBSERVATIONS = frozenset({EvidenceObservation.CORRECT_INDEPENDENT})


class UncertaintyLevel(StrEnum):
    LOW = "low"
    LIMITED = "limited"
    HIGH = "high"


@dataclass(frozen=True, slots=True, kw_only=True)
class RubricResult:
    criterion_id: str
    earned: int
    possible: int
    evidence_refs: Sequence[str] = ()
    # False when the criterion could not be judged on its own (it depends on an earlier
    # error, or the student never reached it). Such criteria produce no skill evidence.
    assessable: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.earned <= self.possible:
            raise ValueError("earned must be between 0 and possible")
        if not self.assessable and self.earned:
            raise ValueError("a criterion that could not be assessed earns no points")


@dataclass(frozen=True, slots=True, kw_only=True)
class SkillEvidence:
    skill_id: str
    observation: EvidenceObservation


@dataclass(frozen=True, slots=True, kw_only=True)
class HintUsage:
    server_hint_count: int
    self_reported_help: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class Uncertainty:
    level: UncertaintyLevel
    reasons: Sequence[str] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Provenance:
    model_version: str
    workflow_version: str
    tool_result_ids: Sequence[str] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Assessment:
    assessment_id: str
    student_id: str
    submission_id: str
    session_id: str
    run_id: str
    status: AssessmentStatus
    question_version: str
    rubric_version: str
    rubric_results: Sequence[RubricResult]
    hint_usage: HintUsage
    skill_evidence: Sequence[SkillEvidence]
    uncertainty: Uncertainty
    provenance: Provenance
    supersedes_assessment_id: str | None = None
    # Student-facing feedback. For insufficient_evidence it is deliberately limited.
    feedback: str = ""
    question_id: str | None = None
    rubric_id: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.status is AssessmentStatus.INSUFFICIENT_EVIDENCE and self.skill_evidence:
            raise ValueError("insufficient_evidence assessments carry no skill evidence")
        if self.hint_usage.server_hint_count > 0 and any(
            e.observation in INDEPENDENT_OBSERVATIONS for e in self.skill_evidence
        ):
            raise ValueError("hint-assisted work cannot be recorded as independent evidence")

    @property
    def updates_mastery(self) -> bool:
        return self.status is AssessmentStatus.ACCEPTED
