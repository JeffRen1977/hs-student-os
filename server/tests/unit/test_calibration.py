"""Step 37: calibration against independent held-out responses, and the prediction gate.
Every input here is synthetic: it exercises the decision logic, it is not evidence."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from app.domain.calibration import (
    MIN_EXAM_OUTCOMES,
    CalibrationResponse,
    CalibrationStatus,
    PredictionEvidence,
    ResponseSource,
    calibrate,
    decide_prediction,
)
from app.domain.types.student import MasteryLevel, PredictionStatus
from scripts.run_calibration import main as run_calibration

SKILLS = [f"calc_bc.skill-{i}" for i in range(5)]
RATES = {MasteryLevel.EMERGING: 0.3, MasteryLevel.DEVELOPING: 0.6, MasteryLevel.PROFICIENT: 0.9}


def responses(rates: dict[MasteryLevel, float] = RATES, per_level: int = 60,
              students: int = 30, source: ResponseSource = ResponseSource.HELD_OUT,
              independent: bool = True) -> list[CalibrationResponse]:  # fmt: skip
    out: list[CalibrationResponse] = []
    counter = itertools.count()
    for level, rate in rates.items():
        correct_n = round(per_level * rate)
        for i in range(per_level):
            n = next(counter)
            out.append(
                CalibrationResponse(
                    student_ref=f"s{n % students}",
                    course_id="calc_bc",
                    skill_id=SKILLS[n % len(SKILLS)],
                    level_before=level,
                    correct=i < correct_n,
                    independent=independent,
                    source=source,
                )
            )
    return out


def test_sufficient_rising_held_out_evidence_calibrates_mastery() -> None:
    report = calibrate("calc_bc", SKILLS, responses(), synthetic=False)
    assert report.status is CalibrationStatus.CALIBRATED and report.monotonic
    assert [round(lv.accuracy or 0, 1) for lv in report.levels] == [0.3, 0.6, 0.9]
    assert report.students == 30 and report.skill_coverage == 1.0


def test_accuracy_that_does_not_rise_is_not_calibrated() -> None:
    flat = {MasteryLevel.EMERGING: 0.6, MasteryLevel.DEVELOPING: 0.5, MasteryLevel.PROFICIENT: 0.7}
    report = calibrate("calc_bc", SKILLS, responses(flat), synthetic=False)
    assert report.status is CalibrationStatus.NOT_CALIBRATED


@pytest.mark.parametrize(
    ("kwargs", "excluded"),
    [
        ({"source": ResponseSource.PRACTICE}, "practice"),
        ({"source": ResponseSource.SELF_REPORTED}, "self_reported"),
        ({"independent": False}, "hint_assisted"),
    ],
)
def test_practice_self_reports_and_hinted_work_are_not_evidence(
    kwargs: dict[str, object], excluded: str
) -> None:
    report = calibrate("calc_bc", SKILLS, responses(**kwargs), synthetic=False)  # type: ignore[arg-type]
    assert report.responses_used == 0 and report.excluded == {excluded: 180}
    assert report.status is CalibrationStatus.INSUFFICIENT_EVIDENCE


def test_small_samples_and_synthetic_data_are_insufficient() -> None:
    small = calibrate("calc_bc", SKILLS, responses(per_level=10, students=5), synthetic=False)
    assert small.status is CalibrationStatus.INSUFFICIENT_EVIDENCE
    assert {"too_few_responses_per_level", "too_few_students"} <= set(small.reasons)
    synthetic = calibrate("calc_bc", SKILLS, responses(), synthetic=True)
    assert synthetic.status is CalibrationStatus.INSUFFICIENT_EVIDENCE
    assert "synthetic_data_is_not_evidence" in synthetic.reasons


def test_other_courses_are_never_pooled() -> None:
    other = [
        CalibrationResponse(student_ref="s", course_id="dsat", skill_id="dsat.x",
                            level_before=MasteryLevel.PROFICIENT, correct=True,
                            independent=True, source=ResponseSource.HELD_OUT)
    ]  # fmt: skip
    assert calibrate("calc_bc", SKILLS, other, synthetic=False).excluded == {"other_course": 1}


def test_prediction_stays_unavailable_on_every_path() -> None:
    calibrated = calibrate("calc_bc", SKILLS, responses(), synthetic=False)
    cases = [
        (None, "not_calibrated"),
        (PredictionEvidence(calibration=calibrate("calc_bc", SKILLS, responses(), synthetic=True)),
         "synthetic_only"),
        (PredictionEvidence(calibration=calibrate("calc_bc", SKILLS, [], synthetic=False)),
         "mastery_not_calibrated"),
        (PredictionEvidence(calibration=calibrated), "no_independent_exam_outcomes"),
        (PredictionEvidence(calibration=calibrated, exam_outcomes=MIN_EXAM_OUTCOMES),
         "prediction_model_not_validated"),
    ]  # fmt: skip
    for evidence, reason in cases:
        decision = decide_prediction("calc_bc", evidence)
        assert decision.status is PredictionStatus.UNAVAILABLE and decision.reason == reason
    # Calibration of one course says nothing about another.
    assert decide_prediction("dsat", PredictionEvidence(calibration=calibrated)).reason == (
        "not_calibrated"
    )


def test_calibration_script_reports_and_refuses_identifying_fields(tmp_path: Path) -> None:
    rows = [
        {"studentRef": r.student_ref, "courseId": r.course_id, "skillId": r.skill_id,
         "levelBefore": r.level_before.value, "correct": r.correct,
         "independent": r.independent, "source": r.source.value}
        for r in responses()
    ]  # fmt: skip
    data = tmp_path / "held_out.jsonl"
    data.write_text("\n".join(json.dumps(r) for r in rows))
    out = tmp_path / "report.md"
    calc_skills = ["--course", "calc_bc", "--input", str(data), "--out", str(out), "--synthetic"]
    assert run_calibration(calc_skills) == 0
    text = out.read_text()
    assert "synthetic (pipeline test, not evidence)" in text
    assert "Exam prediction: **unavailable**" in text
    leaky = tmp_path / "leaky.jsonl"
    leaky.write_text(json.dumps({**rows[0], "email": "x@example.test"}))
    with pytest.raises(SystemExit, match="identifying"):
        run_calibration(["--course", "calc_bc", "--input", str(leaky)])
