"""Guards on the staging seed: it writes to a real project, so every check must hold."""

from __future__ import annotations

import pytest

from app.config import ConfigError
from scripts.seed_staging import PASSWORD_ENV, check_target, foreign_students

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
