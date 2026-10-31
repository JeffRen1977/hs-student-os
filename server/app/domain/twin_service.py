"""Twin (profile / goals / preferences) reads and allowlisted patches (Steps 9–10)."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.catalog import CourseCatalog
from app.domain.ports.repositories import Tx, UnitOfWork
from app.domain.ports.runtime import Clock
from app.domain.types.actor import ActorContext, Permission
from app.domain.types.student import Entitlements, Student

# The only leaf fields a student may change (API.md §1.1). Everything else — studentId,
# entitlements, mastery, assessments, predictionSummary, version — is server-owned.
TWIN_PATCH_ALLOWLIST: Mapping[str, frozenset[str]] = {
    "profile": frozenset({"display_name", "grade", "school", "target_major", "target_schools"}),
    "goals": frozenset({"sat_target", "ap_targets"}),
    "preferences": frozenset(
        {"timezone", "weekly_available_minutes", "selected_courses", "notifications"}
    ),
}
_NOT_NULLABLE = frozenset(
    {
        ("profile", "display_name"),
        ("profile", "grade"),
        ("profile", "target_schools"),
        ("goals", "ap_targets"),
        ("preferences", "timezone"),
        ("preferences", "weekly_available_minutes"),
        ("preferences", "selected_courses"),
        ("preferences", "notifications"),
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class TwinChanges:
    """Leaf-field changes keyed by domain field name, already schema-validated."""

    profile: Mapping[str, object] = field(default_factory=dict)
    goals: Mapping[str, object] = field(default_factory=dict)
    preferences: Mapping[str, object] = field(default_factory=dict)

    def sections(self) -> dict[str, Mapping[str, object]]:
        return {"profile": self.profile, "goals": self.goals, "preferences": self.preferences}


def validate_changes(changes: TwinChanges, catalog: CourseCatalog) -> None:
    total = 0
    for section, values in changes.sections().items():
        unknown = set(values) - TWIN_PATCH_ALLOWLIST[section]
        if unknown:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED, f"{section} fields not patchable: {sorted(unknown)}"
            )
        for name, value in values.items():
            if value is None and (section, name) in _NOT_NULLABLE:
                raise DomainError(ErrorCode.VALIDATION_FAILED, f"{section}.{name} cannot be null")
        total += len(values)
    if total == 0:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "patch must change at least one field")
    selected = changes.preferences.get("selected_courses")
    if isinstance(selected, (list, tuple)):
        unknown_courses = [c for c in selected if catalog.get(str(c)) is None]
        if unknown_courses:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED, f"unknown courses: {sorted(map(str, unknown_courses))}"
            )


class TwinService:
    def __init__(self, uow: UnitOfWork, catalog: CourseCatalog, clock: Clock) -> None:
        self._uow = uow
        self._catalog = catalog
        self._clock = clock

    async def get_twin(self, actor: ActorContext) -> Student:
        actor.require(Permission.TWIN_READ)

        async def read(tx: Tx) -> Student:
            # One transaction = one consistent snapshot of summary + latestEventSequence.
            student = await tx.students.get(actor)
            if student is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Student not found.")
            return student

        return await self._uow.transaction(read)

    async def get_entitlements(self, actor: ActorContext) -> Entitlements:
        actor.require(Permission.TWIN_READ)

        async def read(tx: Tx) -> Entitlements:
            return await tx.students.get_entitlements(actor)

        return await self._uow.transaction(read)

    async def patch_twin(
        self, actor: ActorContext, changes: TwinChanges, *, expected_version: int
    ) -> Student:
        actor.require(Permission.TWIN_WRITE)
        validate_changes(changes, self._catalog)

        async def write(tx: Tx) -> Student:
            current = await tx.students.get(actor)
            if current is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Student not found.")
            if current.version != expected_version:
                raise DomainError(
                    ErrorCode.VERSION_CONFLICT,
                    "The profile changed since it was read. Reload and try again.",
                )
            updated = dataclasses.replace(
                current,
                version=current.version + 1,
                profile=dataclasses.replace(current.profile, **changes.profile),  # type: ignore[arg-type]
                goals=dataclasses.replace(current.goals, **changes.goals),  # type: ignore[arg-type]
                preferences=dataclasses.replace(current.preferences, **changes.preferences),  # type: ignore[arg-type]
            )
            tx.students.save_twin(actor, updated, now=self._clock.now())
            return updated

        return await self._uow.transaction(write)
