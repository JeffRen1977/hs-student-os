"""Mastery calibration and the exam-prediction gate (Step 37).

CLAUDE.md §1.3: exam predictions stay `unavailable` until an independent calibration
pipeline exists. This module *is* that pipeline's decision logic, and it is strict:

- 37.1 Mastery is calibrated only against **independent, held-out** responses: items the
  student answered without hints that were never used to compute their mastery. The
  question asked is simple: do students at a higher mastery level answer held-out items
  correctly more often? Enough responses per level, enough students, enough skills, and
  accuracy that rises with level are all required.
- 37.2 An exam prediction additionally needs representative coverage of the course's
  skills and independent exam outcomes (e.g. reported official scores linked to
  calibrated mastery). Even then no prediction model exists yet, so the result is still
  `unavailable`, with the reason saying what is missing.
- 37.3 Practice performance, self-reported records and predictions are different things.
  Practice (non-held-out) and self-reported responses are counted and excluded from
  calibration evidence; they can never make a prediction available.
- 37.4 Without sufficient evidence the prediction stays `unavailable`. Synthetic data can
  exercise the pipeline but is never evidence.

Pure functions only: no storage, no model calls.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.domain.types.student import MasteryLevel, PredictionStatus, PredictionSummary

LEVEL_ORDER = (
    MasteryLevel.INSUFFICIENT_EVIDENCE,
    MasteryLevel.EMERGING,
    MasteryLevel.DEVELOPING,
    MasteryLevel.PROFICIENT,
)
SCORED_LEVELS = LEVEL_ORDER[1:]  # "insufficient_evidence" makes no claim to calibrate

MIN_RESPONSES_PER_LEVEL = 30
MIN_STUDENTS = 20
MIN_SKILL_COVERAGE = 0.8  # share of the course's skills with held-out evidence
MIN_RESPONSES_PER_SKILL = 5
MIN_EXAM_OUTCOMES = 100


class ResponseSource(StrEnum):
    HELD_OUT = "held_out"  # independent item never used to compute mastery
    PRACTICE = "practice"  # ordinary practice: already inside mastery, not a check of it
    SELF_REPORTED = "self_reported"  # student-reported grades/scores: not an observation


@dataclass(frozen=True, slots=True, kw_only=True)
class CalibrationResponse:
    student_ref: str  # pseudonymous; calibration never needs identity
    course_id: str
    skill_id: str
    level_before: MasteryLevel  # the student's mastery level for the skill at answer time
    correct: bool
    independent: bool  # no hints, first attempt
    source: ResponseSource


class CalibrationStatus(StrEnum):
    CALIBRATED = "calibrated"
    NOT_CALIBRATED = "not_calibrated"  # evidence is sufficient but disagrees with mastery
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True, slots=True, kw_only=True)
class LevelResult:
    level: MasteryLevel
    responses: int
    accuracy: float | None


@dataclass(frozen=True, slots=True, kw_only=True)
class CalibrationReport:
    course_id: str
    status: CalibrationStatus
    reasons: Sequence[str]
    synthetic: bool
    responses_used: int
    students: int
    skill_coverage: float
    levels: Sequence[LevelResult]
    monotonic: bool
    brier: float | None
    excluded: dict[str, int] = field(default_factory=dict)


# Probability each level is taken to claim, used only for the Brier score. A level "claims"
# nothing absolute; the decision uses ordering (monotonicity), the score is reported.
_LEVEL_PROBABILITY = {
    MasteryLevel.EMERGING: 0.4,
    MasteryLevel.DEVELOPING: 0.65,
    MasteryLevel.PROFICIENT: 0.85,
}


def calibrate(
    course_id: str,
    course_skills: Iterable[str],
    responses: Iterable[CalibrationResponse],
    *,
    synthetic: bool,
) -> CalibrationReport:
    skills = set(course_skills)
    excluded: dict[str, int] = {}

    def exclude(reason: str) -> None:
        excluded[reason] = excluded.get(reason, 0) + 1

    used: list[CalibrationResponse] = []
    for r in responses:
        if r.course_id != course_id or r.skill_id not in skills:
            exclude("other_course")  # courses are independent: never pooled
        elif r.source is ResponseSource.PRACTICE:
            exclude("practice")
        elif r.source is ResponseSource.SELF_REPORTED:
            exclude("self_reported")
        elif not r.independent:
            exclude("hint_assisted")
        elif r.level_before is MasteryLevel.INSUFFICIENT_EVIDENCE:
            exclude("no_mastery_claim")
        else:
            used.append(r)

    levels: list[LevelResult] = []
    for level in SCORED_LEVELS:
        rs = [r for r in used if r.level_before is level]
        acc = sum(r.correct for r in rs) / len(rs) if rs else None
        levels.append(LevelResult(level=level, responses=len(rs), accuracy=acc))
    accuracies = [lv.accuracy for lv in levels if lv.accuracy is not None]
    monotonic = len(accuracies) == len(levels) and all(
        a < b for a, b in itertools.pairwise(accuracies)
    )
    per_skill: dict[str, int] = {}
    for r in used:
        per_skill[r.skill_id] = per_skill.get(r.skill_id, 0) + 1
    covered = sum(1 for n in per_skill.values() if n >= MIN_RESPONSES_PER_SKILL)
    coverage = covered / len(skills) if skills else 0.0
    students = len({r.student_ref for r in used})
    brier = (
        sum((_LEVEL_PROBABILITY[r.level_before] - float(r.correct)) ** 2 for r in used) / len(used)
        if used
        else None
    )

    reasons: list[str] = []
    if synthetic:
        reasons.append("synthetic_data_is_not_evidence")
    if any(lv.responses < MIN_RESPONSES_PER_LEVEL for lv in levels):
        reasons.append("too_few_responses_per_level")
    if students < MIN_STUDENTS:
        reasons.append("too_few_students")
    if coverage < MIN_SKILL_COVERAGE:
        reasons.append("insufficient_skill_coverage")
    sufficient = not reasons
    if sufficient and not monotonic:
        status, reasons = CalibrationStatus.NOT_CALIBRATED, ["accuracy_does_not_rise_with_level"]
    elif sufficient:
        status = CalibrationStatus.CALIBRATED
    else:
        status = CalibrationStatus.INSUFFICIENT_EVIDENCE
    return CalibrationReport(
        course_id=course_id,
        status=status,
        reasons=tuple(reasons),
        synthetic=synthetic,
        responses_used=len(used),
        students=students,
        skill_coverage=round(coverage, 3),
        levels=tuple(levels),
        monotonic=monotonic,
        brier=round(brier, 4) if brier is not None else None,
        excluded=excluded,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class PredictionEvidence:
    """What an exam prediction would rest on. `calibration` must be a report a reviewer
    accepted for this course; `exam_outcomes` counts independent official outcomes linked
    to calibrated mastery (none exist yet)."""

    calibration: CalibrationReport | None = None
    exam_outcomes: int = 0


def decide_prediction(course_id: str, evidence: PredictionEvidence | None) -> PredictionSummary:
    """The only way a prediction status is produced (Step 37.4). Today every path ends in
    `unavailable`; the reason names the first missing requirement."""
    cal = evidence.calibration if evidence else None
    if cal is None or cal.course_id != course_id:
        return PredictionSummary(status=PredictionStatus.UNAVAILABLE, reason="not_calibrated")
    if cal.synthetic:
        return PredictionSummary(status=PredictionStatus.UNAVAILABLE, reason="synthetic_only")
    if cal.status is not CalibrationStatus.CALIBRATED:
        return PredictionSummary(
            status=PredictionStatus.UNAVAILABLE, reason="mastery_not_calibrated"
        )
    if cal.skill_coverage < MIN_SKILL_COVERAGE:
        return PredictionSummary(
            status=PredictionStatus.UNAVAILABLE, reason="insufficient_coverage"
        )
    if evidence is None or evidence.exam_outcomes < MIN_EXAM_OUTCOMES:
        return PredictionSummary(
            status=PredictionStatus.UNAVAILABLE, reason="no_independent_exam_outcomes"
        )
    # All evidence present, but no validated score model exists: still unavailable.
    return PredictionSummary(
        status=PredictionStatus.UNAVAILABLE, reason="prediction_model_not_validated"
    )
