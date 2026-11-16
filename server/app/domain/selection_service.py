"""Package selections and the build step (Step 45.4, doc/QUESTION_BANK.md §4.4 and §6).

The organization's content reviewer decides which approved item versions form a package:
sets of up to 10 items (items sharing a passage stay in one set), which sets are starter
tasks and which follow in the practice sequence. Building turns the selection into a
draft package version through the normal upload path (validator report included); the
platform review gate is unchanged.

- Only `approved` item versions can be referenced (409 ITEM_NOT_APPROVED); retired items
  cannot be selected or built. A reference without a version pins the item's current
  approved version at write time, so later edits never change a selection silently.
- Structural problems (set size, duplicate or split items, unknown set ids, items the
  builder cannot express yet) → 409 SELECTION_INVALID with every problem listed.
- Authors read selections; only content reviewers write and build them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from app.domain.bank_builder import BuildError, build_package
from app.domain.commands import CommandKey, Outcome
from app.domain.errors import DomainError, ErrorCode
from app.domain.package_service import PackageService
from app.domain.ports.bank import BankTx, BankUnitOfWork
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.types.actor import Permission, PlatformActor
from app.domain.types.bank import (
    MAX_SELECTION_SETS,
    MAX_SET_ITEMS,
    BankItemState,
    BankItemVersion,
    BankPassage,
    ItemRef,
    ItemType,
    Selection,
    SelectionSet,
    SourceType,
)
from app.domain.types.common import IdempotencyRecord
from app.domain.types.package import PackageVersion, semver_key

SELECTION_RESOURCE = "bank_selection"
SET_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
MAX_STARTER = 20
MAX_SEQUENCE = 200


@dataclass(frozen=True, slots=True, kw_only=True)
class SetInput:
    set_id: str
    title: str
    task_title: str
    duration_min: int
    items: Sequence[tuple[str, int | None]]  # (itemId, version or None = current approved)
    skill_ids: Sequence[str] = ()
    difficulty: str = "medium"


@dataclass(frozen=True, slots=True, kw_only=True)
class SelectionInput:
    name: str
    sets: Sequence[SetInput]
    starter_set_ids: Sequence[str] = ()
    sequence_set_ids: Sequence[str] = ()
    source_type: SourceType = SourceType.ORIGINAL
    source_author: str | None = None
    source_license: str | None = None
    added_skills: Sequence[Mapping[str, str]] = ()  # skills the base package lacks (40B)


@dataclass(frozen=True, slots=True, kw_only=True)
class BuildResult:
    selection: Selection
    package: PackageVersion


def _invalid(problems: Sequence[str]) -> DomainError:
    return DomainError(ErrorCode.SELECTION_INVALID, "Selection problems: " + "; ".join(problems))


def _not_found() -> DomainError:
    return DomainError(ErrorCode.NOT_FOUND, "Selection not found.")


class SelectionService:
    def __init__(
        self, uow: BankUnitOfWork, packages: PackageService, clock: Clock, ids: IdFactory
    ) -> None:
        self._uow = uow
        self._packages = packages
        self._clock = clock
        self._ids = ids

    # ---- Reads ---------------------------------------------------------------------------

    async def list(self, actor: PlatformActor) -> Sequence[Selection]:
        actor.require(Permission.BANK_AUTHOR)
        org = _org(actor)

        async def read(tx: BankTx) -> Sequence[Selection]:
            return await tx.selections.list_for_org(org)

        return await self._uow.transaction(read)

    async def get(self, actor: PlatformActor, selection_id: str) -> Selection:
        actor.require(Permission.BANK_AUTHOR)
        org = _org(actor)

        async def read(tx: BankTx) -> Selection:
            return await _own(tx, org, selection_id)

        return await self._uow.transaction(read)

    # ---- Content reviewer commands --------------------------------------------------------

    async def create(
        self, actor: PlatformActor, course_id: str, inp: SelectionInput, cmd: CommandKey
    ) -> Outcome[Selection]:
        actor.require(Permission.BANK_REVIEW)
        org = _org(actor)
        _check_shape(inp)

        async def write(tx: BankTx) -> Outcome[Selection]:
            replay = await _replay(tx, actor, cmd)
            if replay is not None:
                return Outcome(
                    value=await _own(tx, org, replay.resource_id),
                    replayed=True,
                    created=replay.response_status == 201,
                )
            sets = await _resolve(tx, org, course_id, inp.sets)
            now = self._clock.now()
            selection = Selection(
                selection_id=self._ids.new("sel"),
                org_id=org,
                course_id=course_id,
                name=inp.name,
                sets=sets,
                starter_set_ids=tuple(inp.starter_set_ids),
                sequence_set_ids=tuple(inp.sequence_set_ids),
                created_by=actor.actor_id,
                created_at=now,
                updated_at=now,
                source_type=inp.source_type,
                source_author=inp.source_author,
                source_license=inp.source_license,
                added_skills=tuple(dict(k) for k in inp.added_skills),
            )
            tx.selections.save(selection)
            _remember(tx, actor, cmd, selection.selection_id, 201, now)
            return Outcome(value=selection, created=True)

        return await self._uow.transaction(write)

    async def update(
        self,
        actor: PlatformActor,
        selection_id: str,
        expected_revision: int,
        inp: SelectionInput,
        cmd: CommandKey,
    ) -> Outcome[Selection]:
        """Replace the selection's name, sets, task lists and source fields."""
        actor.require(Permission.BANK_REVIEW)
        org = _org(actor)
        _check_shape(inp)

        async def write(tx: BankTx) -> Outcome[Selection]:
            replay = await _replay(tx, actor, cmd)
            if replay is not None:
                return Outcome(
                    value=await _own(tx, org, replay.resource_id), replayed=True, created=False
                )
            current = await _own(tx, org, selection_id)
            if current.revision != expected_revision:
                raise DomainError(
                    ErrorCode.VERSION_CONFLICT,
                    f"The selection changed (revision {current.revision}); reload and try again.",
                )
            sets = await _resolve(tx, org, current.course_id, inp.sets)
            now = self._clock.now()
            selection = replace(
                current,
                name=inp.name,
                sets=sets,
                starter_set_ids=tuple(inp.starter_set_ids),
                sequence_set_ids=tuple(inp.sequence_set_ids),
                source_type=inp.source_type,
                source_author=inp.source_author,
                source_license=inp.source_license,
                added_skills=tuple(dict(k) for k in inp.added_skills),
                built_package_version=None,
                built_by=None,
                built_at=None,
                revision=current.revision + 1,
                updated_at=now,
            )
            tx.selections.save(selection)
            _remember(tx, actor, cmd, selection_id, 200, now)
            return Outcome(value=selection, created=False)

        return await self._uow.transaction(write)

    async def build(
        self, actor: PlatformActor, selection_id: str, version: str, cmd: CommandKey
    ) -> Outcome[BuildResult]:
        """Build a draft package version from the selection and upload it (validator report
        included). The base — manifest, tutor prompt, skills — is the latest package
        version of the course in this organization."""
        actor.require(Permission.BANK_REVIEW)
        actor.require(Permission.PACKAGES_AUTHOR)
        org = _org(actor)
        try:
            semver_key(version)
        except ValueError as exc:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED, "version must be MAJOR.MINOR.PATCH"
            ) from exc

        async def gather(
            tx: BankTx,
        ) -> (
            tuple[Selection, dict[tuple[str, int], BankItemVersion], dict[str, BankPassage]]
            | Selection
        ):
            replay = await _replay(tx, actor, cmd)
            if replay is not None:
                return await _own(tx, org, replay.resource_id)
            selection = await _own(tx, org, selection_id)
            versions, problems = await _versions(tx, org, selection.sets)
            if problems:
                raise _invalid(problems)
            passages: dict[str, BankPassage] = {}
            for v in versions.values():
                pid = v.content.passage_id
                if pid and pid not in passages:
                    p = await tx.passages.get(org, pid)
                    if p is not None:
                        passages[pid] = p
            return selection, versions, passages

        gathered = await self._uow.transaction(gather)
        if isinstance(gathered, Selection):  # replay of a finished build
            pkg = await self._packages.get_own(actor, gathered.course_id, version)
            return Outcome(
                value=BuildResult(selection=gathered, package=pkg), replayed=True, created=True
            )
        selection, versions, passages = gathered
        base = await self._base_package(actor, selection.course_id)
        try:
            raw = build_package(base, selection, versions, passages, version)
        except BuildError as exc:
            raise _invalid(exc.problems) from exc
        upload_cmd = CommandKey(
            scope=cmd.scope + " → upload", key=cmd.key, request_digest=cmd.request_digest
        )
        uploaded = await self._packages.upload(actor, raw, upload_cmd)

        async def mark(tx: BankTx) -> Selection:
            replay = await _replay(tx, actor, cmd)
            if replay is not None:
                return await _own(tx, org, replay.resource_id)
            current = await _own(tx, org, selection_id)
            if current.revision != selection.revision:
                raise DomainError(
                    ErrorCode.VERSION_CONFLICT,
                    "The selection changed during the build; reload and build a new version.",
                )
            now = self._clock.now()
            done = replace(
                current,
                built_package_version=version,
                built_by=actor.actor_id,
                built_at=now,
                revision=current.revision + 1,
                updated_at=now,
            )
            tx.selections.save(done)
            _remember(tx, actor, cmd, selection_id, 201, now)
            return done

        built = await self._uow.transaction(mark)
        return Outcome(value=BuildResult(selection=built, package=uploaded.value), created=True)

    async def base_skills(
        self, actor: PlatformActor, course_id: str
    ) -> Sequence[Mapping[str, str]]:
        """The skills of the course's latest package in the organization ([] if none);
        the authoring assistant snapshots them for skill tags (Step 40)."""
        try:
            base = await self._base_package(actor, course_id)
        except DomainError:
            return []
        return [
            {"skillId": str(k["skillId"]), "name": str(k.get("name", ""))}
            for k in base.get("skills", [])
        ]

    async def _base_package(self, actor: PlatformActor, course_id: str) -> Mapping[str, Any]:
        own = [v for v in await self._packages.list_own(actor) if v.course_id == course_id]
        if not own:
            raise _invalid(
                [
                    f"upload a first package for {course_id}: it defines the manifest, skills and "
                    "tutor prompt the build uses"
                ]
            )
        latest = max(own, key=lambda v: semver_key(v.version))
        full = await self._packages.get_own(actor, course_id, latest.version)
        data: Mapping[str, Any] = json.loads(full.package_json)
        return data


# ---- Helpers ------------------------------------------------------------------------------------


def _org(actor: PlatformActor) -> str:
    if actor.org_id is None:
        raise DomainError(ErrorCode.FORBIDDEN, "This account has no organization bank.")
    return actor.org_id


async def _own(tx: BankTx, org: str, selection_id: str) -> Selection:
    selection = await tx.selections.get(org, selection_id)
    if selection is None:
        raise _not_found()
    return selection


def _check_shape(inp: SelectionInput) -> None:
    problems: list[str] = []
    if not inp.name.strip():
        problems.append("the selection needs a name")
    if not inp.sets:
        problems.append("the selection needs at least one set")
    if len(inp.sets) > MAX_SELECTION_SETS:
        problems.append(f"at most {MAX_SELECTION_SETS} sets")
    ids = [s.set_id for s in inp.sets]
    for sid in ids:
        if not SET_ID.fullmatch(sid):
            problems.append(f"setId {sid!r} must be lowercase letters, digits and hyphens")
    dupes = sorted({s for s in ids if ids.count(s) > 1})
    if dupes:
        problems.append("duplicate setIds: " + ", ".join(dupes))
    refs = [i for s in inp.sets for i, _ in s.items]
    repeated = sorted({i for i in refs if refs.count(i) > 1})
    if repeated:
        problems.append("items used more than once: " + ", ".join(repeated))
    for s in inp.sets:
        if not s.items or len(s.items) > MAX_SET_ITEMS:
            problems.append(f"set {s.set_id}: 1 to {MAX_SET_ITEMS} items")
        if not s.title.strip() or not s.task_title.strip():
            problems.append(f"set {s.set_id}: title and taskTitle are required")
        if not 5 <= s.duration_min <= 120:
            problems.append(f"set {s.set_id}: durationMin must be 5 to 120")
        if s.difficulty not in ("easy", "medium", "hard"):
            problems.append(f"set {s.set_id}: difficulty must be easy, medium or hard")
    known = set(ids)
    for label, chosen, limit in (
        ("starterSetIds", inp.starter_set_ids, MAX_STARTER),
        ("sequenceSetIds", inp.sequence_set_ids, MAX_SEQUENCE),
    ):
        unknown = [s for s in chosen if s not in known]
        if unknown:
            problems.append(f"{label} not in the selection: " + ", ".join(unknown))
        if len(chosen) > limit or len(set(chosen)) != len(chosen):
            problems.append(f"{label}: at most {limit}, no repeats")
    both = set(inp.starter_set_ids) & set(inp.sequence_set_ids)
    if both:
        problems.append(
            "a set is both a starter task and in the sequence: " + ", ".join(sorted(both))
        )
    if problems:
        raise _invalid(problems)


async def _resolve(
    tx: BankTx, org: str, course_id: str, sets: Sequence[SetInput]
) -> tuple[SelectionSet, ...]:
    """Pin item versions and check every reference against the bank."""
    resolved: list[SelectionSet] = []
    not_approved: list[str] = []
    for s in sets:
        refs: list[ItemRef] = []
        for item_id, number in s.items:
            item = await tx.items.get(org, item_id)
            if item is None:
                raise DomainError(ErrorCode.NOT_FOUND, f"Item {item_id} not found.")
            if item.course_id is not None and item.course_id != course_id:
                raise _invalid([f"{item_id} belongs to course {item.course_id}, not {course_id}"])
            pinned = number if number is not None else item.approved_version
            if pinned is None or item.state is BankItemState.RETIRED:
                not_approved.append(item_id)
                continue
            refs.append(ItemRef(item_id=item_id, version=pinned))
        resolved.append(
            SelectionSet(
                set_id=s.set_id,
                title=s.title,
                task_title=s.task_title,
                duration_min=s.duration_min,
                items=tuple(refs),
                skill_ids=tuple(s.skill_ids),
                difficulty=s.difficulty,
            )
        )
    if not_approved:
        raise DomainError(
            ErrorCode.ITEM_NOT_APPROVED,
            "Only approved, unretired items can be selected: " + ", ".join(not_approved),
        )
    _, problems = await _versions(tx, org, resolved)
    if problems:
        raise _invalid(problems)
    return tuple(resolved)


async def _versions(
    tx: BankTx, org: str, sets: Sequence[SelectionSet]
) -> tuple[dict[tuple[str, int], BankItemVersion], list[str]]:
    """The referenced versions, plus problems: unapproved/retired references, items the
    builder cannot express, and a passage split across sets."""
    versions: dict[tuple[str, int], BankItemVersion] = {}
    problems: list[str] = []
    passage_set: dict[str, str] = {}
    for s in sets:
        for ref in s.items:
            item = await tx.items.get(org, ref.item_id)
            v = await tx.items.get_version(org, ref.item_id, ref.version)
            if item is None or v is None:
                problems.append(f"{ref.item_id} v{ref.version} does not exist")
                continue
            if v.state is not BankItemState.APPROVED or item.state is BankItemState.RETIRED:
                problems.append(
                    f"{ref.item_id} v{ref.version} is not an approved, unretired version"
                )
                continue
            if v.content.item_type is not ItemType.MC:
                problems.append(
                    f"{ref.item_id}: student-produced-response items cannot be built yet"
                )
            pid = v.content.passage_id
            if pid:
                other = passage_set.setdefault(pid, s.set_id)
                if other != s.set_id:
                    problems.append(f"passage {pid} is split across sets {other} and {s.set_id}")
            versions[(ref.item_id, ref.version)] = v
    return versions, problems


async def _replay(tx: BankTx, actor: PlatformActor, cmd: CommandKey) -> IdempotencyRecord | None:
    record = await tx.idempotency.get(actor.actor_id, cmd.key_hash(actor))
    if record is None:
        return None
    if record.scope != cmd.scope or record.request_digest != cmd.request_digest:
        raise DomainError(
            ErrorCode.IDEMPOTENCY_CONFLICT,
            "This Idempotency-Key was already used with a different request.",
        )
    return record


def _remember(
    tx: BankTx, actor: PlatformActor, cmd: CommandKey, selection_id: str, status: int, now: datetime
) -> None:
    tx.idempotency.save(
        actor.actor_id,
        IdempotencyRecord(
            key_hash=cmd.key_hash(actor),
            scope=cmd.scope,
            request_digest=cmd.request_digest,
            resource_type=SELECTION_RESOURCE,
            resource_id=selection_id,
            response_status=status,
            created_at=now,
        ),
    )
