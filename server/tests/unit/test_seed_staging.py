"""Guards on the staging seed: it writes to a real project, so every check must hold."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.adapters.seed_documents import build_seed_documents
from app.config import ConfigError
from app.registries.fixtures import load_seed_students
from scripts.seed_staging import (
    PASSWORD_ENV,
    check_target,
    foreign_students,
    without_existing_runtime_state,
)

GOOD = {PASSWORD_ENV: "synthetic-test-pw-1"}


def test_named_twice_real_project_with_password_passes() -> None:
    assert check_target("hs-student-os", "hs-student-os", GOOD) == GOOD[PASSWORD_ENV]


@pytest.mark.parametrize(
    ("project", "confirm", "env", "message"),
    [
        ("hs-student-os", "hs-student-os-x", GOOD, "same project"),
        ("demo-hs-student-os", "demo-hs-student-os", GOOD, "emulator-only"),
        ("hs-student-os", "hs-student-os", GOOD | {"FIRESTORE_EMULATOR_HOST": "x:1"}, "unset"),
        ("hs-student-os", "hs-student-os", {}, PASSWORD_ENV),
        ("hs-student-os", "hs-student-os", {PASSWORD_ENV: "short"}, PASSWORD_ENV),
    ],
)
def test_unsafe_targets_are_refused(
    project: str, confirm: str, env: dict[str, str], message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        check_target(project, confirm, env)


def test_any_non_fixture_student_stops_the_seed() -> None:
    assert foreign_students(["stu_alex", "stu_beth"], ["stu_alex", "stu_beth"]) == []
    assert foreign_students([], ["stu_alex"]) == []
    assert foreign_students(["stu_alex", "real_kid"], ["stu_alex", "stu_beth"]) == ["real_kid"]


def test_reseeding_never_resets_runtime_state() -> None:
    # Found in staging 2026-11-07: a re-seed reset nextSequence to 1 while earlier events
    # stayed, so new events reused sequence numbers and course-metrics skipped them.
    docs = build_seed_documents(load_seed_students(), now=datetime(2026, 11, 7, tzinfo=UTC))
    state = [p for p in docs if p.endswith(("/eventState/current", "/planState/current"))]
    assert "students/stu_alex/eventState/current" in state

    fresh, kept = without_existing_runtime_state(docs, [])
    assert fresh == docs and kept == set()  # a new project gets everything

    existing = [*state, "students/stu_alex", "students/stu_alex/tasks/task_alex_calc_01"]
    reseed, kept = without_existing_runtime_state(docs, existing)
    assert kept == set(state)
    assert not any(p in reseed for p in state)
    assert "students/stu_alex" in reseed  # fixture documents are still refreshed
