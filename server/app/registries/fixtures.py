"""Load synthetic seed fixtures (`server/fixtures/`)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.registries.content import ContentError, load_json
from app.schemas.fixtures import EntitlementFixture, StudentFixture

DEFAULT_FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures"


@dataclass(frozen=True, slots=True)
class SeedStudent:
    student: StudentFixture
    entitlements: EntitlementFixture


def load_seed_students(root: Path = DEFAULT_FIXTURE_ROOT) -> list[SeedStudent]:
    students = {
        fx.student_id: fx
        for fx in (
            StudentFixture.model_validate(load_json(p))
            for p in sorted((root / "students").glob("*.json"))
        )
    }
    grants = {
        fx.student_id: fx
        for fx in (
            EntitlementFixture.model_validate(load_json(p))
            for p in sorted((root / "entitlements").glob("*.json"))
        )
    }
    if set(students) != set(grants):
        raise ContentError("every fixture student needs exactly one entitlement fixture")
    return [SeedStudent(students[sid], grants[sid]) for sid in sorted(students)]
