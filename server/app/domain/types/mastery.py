"""Mastery is a projection of accepted assessments (BACKEND.md §3, §6).

Each skill's projection keeps the contributions that produced it, keyed by evidence
application id (`{assessmentId}:{skillId}`). Applying the same evidence twice is therefore
a no-op, a regrade replaces the superseded contribution instead of stacking, and the whole
projection can be rebuilt from accepted assessments.

The level rules below are uncalibrated product rules (version `mastery-rules-v2`); they are
not an exam prediction. Independent evidence is counted per *question*, and only from the
first graded attempt at that question: answering the same question again in a new session
(after its feedback, or by repeating the same answer) is not a new independent measurement.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.domain.types.assessment import EvidenceObservation, UncertaintyLevel
from app.domain.types.student import MasteryLevel

MASTERY_RULE_VERSION = "mastery-rules-v2"
PROFICIENT_INDEPENDENT_COUNT = 3
RECENT_WINDOW = 3


def evidence_application_id(assessment_id: str, skill_id: str) -> str:
    return f"{assessment_id}:{skill_id}"


@dataclass(frozen=True, slots=True, kw_only=True)
class MasteryContribution:
    assessment_id: str
    question_id: str
    observation: EvidenceObservation
    recorded_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class MasteryState:
    skill_id: str
    course_id: str
    level: MasteryLevel
    independent_evidence_count: int
    evidence_count: int
    coverage: int  # distinct questions contributing evidence
    uncertainty: UncertaintyLevel
    updated_at: datetime | None
    contributions: Mapping[str, MasteryContribution] = field(default_factory=dict)
    rule_version: str = MASTERY_RULE_VERSION


def empty_mastery(skill_id: str, course_id: str) -> MasteryState:
    return MasteryState(
        skill_id=skill_id,
        course_id=course_id,
        level=MasteryLevel.INSUFFICIENT_EVIDENCE,
        independent_evidence_count=0,
        evidence_count=0,
        coverage=0,
        uncertainty=UncertaintyLevel.HIGH,
        updated_at=None,
    )


def project(
    skill_id: str,
    course_id: str,
    contributions: Mapping[str, MasteryContribution],
    *,
    now: datetime | None,
) -> MasteryState:
    """Pure projection: the same contributions always give the same state."""
    items: Sequence[MasteryContribution] = sorted(
        contributions.values(), key=lambda c: (c.recorded_at, c.assessment_id)
    )
    first_attempts: dict[str, MasteryContribution] = {}
    for c in items:
        first_attempts.setdefault(c.question_id, c)
    independent = sum(
        1
        for c in first_attempts.values()
        if c.observation is EvidenceObservation.CORRECT_INDEPENDENT
    )
    recent = items[-RECENT_WINDOW:]
    if not items:
        level = MasteryLevel.INSUFFICIENT_EVIDENCE
    elif independent == 0:
        level = MasteryLevel.EMERGING
    elif independent >= PROFICIENT_INDEPENDENT_COUNT and all(
        c.observation is not EvidenceObservation.INCORRECT for c in recent
    ):
        level = MasteryLevel.PROFICIENT
    else:
        level = MasteryLevel.DEVELOPING
    if len(items) < 2:
        uncertainty = UncertaintyLevel.HIGH
    elif independent < PROFICIENT_INDEPENDENT_COUNT:
        uncertainty = UncertaintyLevel.LIMITED
    else:
        uncertainty = UncertaintyLevel.LOW
    return MasteryState(
        skill_id=skill_id,
        course_id=course_id,
        level=level,
        independent_evidence_count=independent,
        evidence_count=len(items),
        coverage=len({c.question_id for c in items}),
        uncertainty=uncertainty,
        updated_at=now,
        contributions=dict(contributions),
    )
