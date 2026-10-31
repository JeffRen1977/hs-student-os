"""Step 4: synthetic students, entitlements, and their seed documents."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.adapters.seed_documents import build_seed_documents
from app.domain.types.course import EnrollmentStatus
from app.domain.types.student import PredictionStatus
from app.registries.content import load_content
from app.registries.fixtures import DEFAULT_FIXTURE_ROOT, SeedStudent, load_seed_students
from app.schemas.fixtures import StudentFixture


@pytest.fixture(scope="module")
def seeds() -> list[SeedStudent]:
    return load_seed_students()


def by_id(seeds: list[SeedStudent]) -> dict[str, SeedStudent]:
    return {s.student.student_id: s for s in seeds}


def test_two_isolated_students(seeds: list[SeedStudent]) -> None:
    students = by_id(seeds)
    assert set(students) == {"stu_alex", "stu_beth"}
    alex, beth = students["stu_alex"].student, students["stu_beth"].student
    assert (alex.profile.grade, alex.preferences.timezone) == (11, "America/Los_Angeles")
    assert (beth.profile.grade, beth.preferences.timezone) == (10, "America/New_York")
    assert alex.email != beth.email
    assert alex.preferences != beth.preferences


def test_entitlements_differ_and_are_separate(seeds: list[SeedStudent]) -> None:
    students = by_id(seeds)
    alex, beth = students["stu_alex"].entitlements, students["stu_beth"].entitlements
    assert alex.entitlements.ap_courses == ["calc_bc"] and alex.entitlements.dsat
    assert beth.entitlements.ap_courses == ["calc_bc"] and not beth.entitlements.dsat
    raw = json.loads((DEFAULT_FIXTURE_ROOT / "students/student-a.json").read_text())
    assert "entitlements" not in raw and "subscriptions" not in raw


def test_student_fixture_cannot_embed_entitlements() -> None:
    raw = json.loads((DEFAULT_FIXTURE_ROOT / "students/student-a.json").read_text())
    raw["entitlements"] = {"apCourses": ["apush"], "dsat": True, "admissions": True}
    with pytest.raises(ValidationError):
        StudentFixture.model_validate(raw)


def test_predictions_are_unavailable(seeds: list[SeedStudent]) -> None:
    for seed in seeds:
        assert seed.student.prediction_summary
        for prediction in seed.student.prediction_summary.values():
            assert prediction.status is PredictionStatus.UNAVAILABLE


def test_no_legacy_score_fields_anywhere() -> None:
    for path in DEFAULT_FIXTURE_ROOT.rglob("*.json"):
        text = path.read_text()
        for legacy in ('"predicted"', '"target"', '"scoreDelta"', '"gpa"', '"subscriptions"'):
            assert legacy not in text, f"{path.name} contains {legacy}"


def test_fixtures_are_synthetic_only() -> None:
    raw = json.loads((DEFAULT_FIXTURE_ROOT / "students/student-a.json").read_text())
    with pytest.raises(ValidationError):
        StudentFixture.model_validate({**raw, "email": "alex@gmail.com"})
    with pytest.raises(ValidationError):
        StudentFixture.model_validate({**raw, "synthetic": False})
    with pytest.raises(ValidationError):
        StudentFixture.model_validate(
            {**raw, "predictionSummary": {"calc_bc": {"status": "available", "reason": "4.5"}}}
        )


def test_enrollments_are_active_entitled_courses(seeds: list[SeedStudent]) -> None:
    content = load_content()
    for seed in seeds:
        for enrollment in seed.student.enrollments:
            assert enrollment.status is EnrollmentStatus.ACTIVE
            assert enrollment.course_id in content.active_course_ids()
            assert enrollment.course_id in seed.entitlements.entitlements.ap_courses


def test_selected_planned_course_is_not_treated_as_active() -> None:
    content = load_content()
    assert "apush" in content.packs and "apush" not in content.active_course_ids()


def test_seed_documents_are_scoped_per_student(seeds: list[SeedStudent]) -> None:
    docs = build_seed_documents(seeds, now=datetime(2026, 10, 30, tzinfo=UTC))
    for path, data in docs.items():
        owner = path.split("/")[1]
        assert path.startswith(f"students/{owner}")
        if "studentId" in data:
            assert data["studentId"] == owner
    assert docs["students/stu_alex/access/current"]["dsat"] is True
    assert docs["students/stu_beth/access/current"]["dsat"] is False
    assert "entitlements" not in docs["students/stu_alex"]
    assert docs["students/stu_alex/enrollments/calc_bc"]["status"] == "active"
    assert docs["students/stu_alex/eventState/current"] == {"nextSequence": 1}
    assert docs["students/stu_alex/tasks/task_alex_calc_01"]["status"] == "PLANNED"
    assert docs["students/stu_beth/tasks/task_beth_calc_01"]["studentId"] == "stu_beth"


def test_task_fixtures_belong_to_enrolled_courses(seeds: list[SeedStudent]) -> None:
    for seed in seeds:
        enrolled = {e.course_id for e in seed.student.enrollments}
        assert seed.tasks, seed.student.student_id
        for task in seed.tasks:
            assert task.student_id == seed.student.student_id
            assert task.course_id in enrolled


def test_seed_rejects_mismatched_entitlement_owner(seeds: list[SeedStudent]) -> None:
    alex, beth = by_id(seeds)["stu_alex"], by_id(seeds)["stu_beth"]
    with pytest.raises(ValueError, match="different student"):
        build_seed_documents([SeedStudent(alex.student, beth.entitlements)], now=datetime.now(UTC))
