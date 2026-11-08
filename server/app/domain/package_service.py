"""Authoring, review and publishing of course packages (Step 26).

    upload (author) ──► draft ──submit──► submitted ──approve──► approved ──activate──► active
                                              └──reject──► rejected       active ──► superseded
                                                                          active ──retire──► retired

- Authors act only within their own organization; another organization's packages,
  and courseIds it owns, are invisible (404) or unavailable (409 COURSE_ID_TAKEN).
- Reviewers approve or reject; only platform admins activate or retire. Approval requires a
  valid validator report, every key-scored evaluation case passing, a license
  attestation, and — when the evaluation set has model-graded cases — an attestation that
  the reviewer ran them.
- Every transition is appended to the version's history (who, when, notes).
- After a commit that changes what students can use, the runtime registry is refreshed.
  A new version never changes open sessions: each Session pins its package version.

Package records never contain student data, and these services never read it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from app.domain.commands import CommandKey, Outcome
from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.packages import (
    ContentActivation,
    PackageTx,
    PackageUnitOfWork,
    PackageValidator,
)
from app.domain.ports.runtime import Clock
from app.domain.types.actor import Permission, PlatformActor
from app.domain.types.common import IdempotencyRecord
from app.domain.types.course_metrics import CourseMetrics
from app.domain.types.package import (
    PACKAGE_TRANSITIONS,
    CourseState,
    PackageCourse,
    PackageStatus,
    PackageVersion,
    ReviewDecision,
    StatusChange,
    semver_key,
)

PACKAGE_RESOURCE = "package_version"


@dataclass(frozen=True, slots=True, kw_only=True)
class ApproveInput:
    notes: str
    license_attested: bool
    model_evaluation_attested: bool


def _not_found() -> DomainError:
    return DomainError(ErrorCode.NOT_FOUND, "Package not found.")


def _transition(
    v: PackageVersion, to: PackageStatus, actor_id: str, now: datetime, notes: str = ""
) -> PackageVersion:
    if to not in PACKAGE_TRANSITIONS[v.status]:
        raise DomainError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"A {v.status.value} package cannot become {to.value}.",
        )
    change = StatusChange(
        from_status=v.status, to_status=to, actor_id=actor_id, at=now, notes=notes
    )
    return replace(v, status=to, updated_at=now, history=(*v.history, change))


async def _replay(tx: PackageTx, actor: PlatformActor, cmd: CommandKey) -> IdempotencyRecord | None:
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
    tx: PackageTx,
    actor: PlatformActor,
    cmd: CommandKey,
    v: PackageVersion,
    status: int,
    now: datetime,
) -> None:
    tx.idempotency.save(
        actor.actor_id,
        IdempotencyRecord(
            key_hash=cmd.key_hash(actor),
            scope=cmd.scope,
            request_digest=cmd.request_digest,
            resource_type=PACKAGE_RESOURCE,
            resource_id=v.key,
            response_status=status,
            created_at=now,
        ),
    )


async def _replayed_version(tx: PackageTx, record: IdempotencyRecord) -> PackageVersion:
    course_id, _, version = record.resource_id.partition("@")
    v = await tx.versions.get(course_id, version)
    if v is None:  # pragma: no cover - versions are never deleted
        raise _not_found()
    return v


class PackageService:
    def __init__(
        self,
        uow: PackageUnitOfWork,
        validator: PackageValidator,
        activation: ContentActivation,
        clock: Clock,
        *,
        reserved_course_ids: frozenset[str],
    ) -> None:
        """`reserved_course_ids`: bundled first-party courses no author may claim."""
        self._uow = uow
        self._validator = validator
        self._activation = activation
        self._clock = clock
        self._reserved = reserved_course_ids

    # ---- Author ------------------------------------------------------------------------

    async def upload(
        self, actor: PlatformActor, raw: Mapping[str, Any], cmd: CommandKey
    ) -> Outcome[PackageVersion]:
        """Store a package version as `draft` with its validator report.

        Validation is pure and runs before the transaction (no external calls inside).
        Re-uploading the same version replaces it only while it is still a draft.
        """
        actor.require(Permission.PACKAGES_AUTHOR)
        assert actor.org_id is not None
        org_id = actor.org_id
        check = self._validator.validate(raw)
        if check.course_id is None or check.version is None:
            paths = ", ".join(sorted({e.path for e in check.report.errors})) or "manifest"
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                "The package needs manifest.courseId and manifest.version. Problems at: " + paths,
            )
        course_id, version = check.course_id, check.version
        try:
            new_key = semver_key(version)
        except ValueError as exc:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED, "manifest.version must be MAJOR.MINOR.PATCH"
            ) from exc

        async def write(tx: PackageTx) -> Outcome[PackageVersion]:
            replay = await _replay(tx, actor, cmd)
            if replay is not None:
                return Outcome(value=await _replayed_version(tx, replay), replayed=True,
                               created=replay.response_status == 201)  # fmt: skip
            now = self._clock.now()
            course = await tx.courses.get(course_id)
            if course_id in self._reserved or (course is not None and course.org_id != org_id):
                raise DomainError(
                    ErrorCode.COURSE_ID_TAKEN, "This courseId belongs to another publisher."
                )
            if course is None:
                course = PackageCourse(
                    course_id=course_id, org_id=org_id, state=CourseState.DRAFTING,
                    active_version=None, created_at=now, updated_at=now,
                )  # fmt: skip
                tx.courses.save(course)
            existing = await tx.versions.get(course_id, version)
            if existing is not None and existing.status is not PackageStatus.DRAFT:
                raise DomainError(
                    ErrorCode.PACKAGE_VERSION_EXISTS,
                    f"Version {version} is already {existing.status.value}; upload a new version.",
                )
            released = [
                v.version
                for v in await tx.versions.list_for_course(course_id)
                if v.status is not PackageStatus.DRAFT
            ]
            if any(semver_key(r) >= new_key for r in released):
                raise DomainError(
                    ErrorCode.PACKAGE_VERSION_EXISTS,
                    "The version must be greater than every submitted version: "
                    + max(released, key=semver_key),
                )
            change = StatusChange(
                from_status=None, to_status=PackageStatus.DRAFT, actor_id=actor.actor_id, at=now,
                notes="replaced draft" if existing else "uploaded",
            )  # fmt: skip
            v = PackageVersion(
                course_id=course_id,
                version=version,
                org_id=org_id,
                status=PackageStatus.DRAFT,
                title=check.title,
                package_json=check.canonical_json,
                content_hash=check.content_hash,
                report=check.report,
                uploaded_by=actor.actor_id,
                created_at=existing.created_at if existing else now,
                updated_at=now,
                history=(*(existing.history if existing else ()), change),
            )
            tx.versions.save(v)
            status = 200 if existing else 201
            _remember(tx, actor, cmd, v, status, now)
            return Outcome(value=v, created=existing is None)

        return await self._uow.transaction(write)

    async def submit(
        self, actor: PlatformActor, course_id: str, version: str, cmd: CommandKey
    ) -> Outcome[PackageVersion]:
        actor.require(Permission.PACKAGES_AUTHOR)

        async def write(tx: PackageTx) -> Outcome[PackageVersion]:
            replay = await _replay(tx, actor, cmd)
            if replay is not None:
                return Outcome(
                    value=await _replayed_version(tx, replay), replayed=True, created=False
                )
            v = await self._own(tx, actor, course_id, version)
            if v.status is PackageStatus.DRAFT and not v.report.valid:
                raise DomainError(
                    ErrorCode.PACKAGE_INVALID,
                    f"The validator found {len(v.report.errors)} error(s); "
                    "fix them and upload again.",
                )
            now = self._clock.now()
            v = _transition(v, PackageStatus.SUBMITTED, actor.actor_id, now)
            tx.versions.save(v)
            _remember(tx, actor, cmd, v, 200, now)
            return Outcome(value=v, created=False)

        return await self._uow.transaction(write)

    async def list_own(self, actor: PlatformActor) -> Sequence[PackageVersion]:
        actor.require(Permission.PACKAGES_AUTHOR)
        assert actor.org_id is not None
        org_id = actor.org_id

        async def read(tx: PackageTx) -> Sequence[PackageVersion]:
            return await tx.versions.list_for_org(org_id)

        return await self._uow.transaction(read)

    async def get_own(self, actor: PlatformActor, course_id: str, version: str) -> PackageVersion:
        actor.require(Permission.PACKAGES_AUTHOR)

        async def read(tx: PackageTx) -> PackageVersion:
            return await self._own(tx, actor, course_id, version)

        return await self._uow.transaction(read)

    async def _own(
        self, tx: PackageTx, actor: PlatformActor, course_id: str, version: str
    ) -> PackageVersion:
        v = await tx.versions.get(course_id, version)
        if v is None or v.org_id != actor.org_id:
            raise _not_found()  # another organization's package does not exist for you
        return v

    async def course_metrics(self, actor: PlatformActor, course_id: str) -> CourseMetrics:
        """Aggregates for a course the author's organization owns (Step 34.4). Another
        organization's course, or a bundled one, is not found. The caller decides how much
        to show; below `MIN_COHORT` students the API returns nothing but the threshold."""
        actor.require(Permission.PACKAGES_AUTHOR)

        async def read(tx: PackageTx) -> CourseMetrics:
            course = await tx.courses.get(course_id)
            if course is None or course.org_id != actor.org_id:
                raise _not_found()
            return await tx.metrics.get(course_id) or CourseMetrics(course_id=course_id)

        return await self._uow.transaction(read)

    # ---- Platform reviewer ---------------------------------------------------------------

    async def review_queue(
        self, actor: PlatformActor, statuses: Sequence[PackageStatus]
    ) -> Sequence[PackageVersion]:
        actor.require(Permission.PACKAGES_REVIEW)
        wanted = [s for s in statuses if s is not PackageStatus.DRAFT]  # drafts stay private

        async def read(tx: PackageTx) -> Sequence[PackageVersion]:
            return await tx.versions.list_by_status(wanted) if wanted else []

        return await self._uow.transaction(read)

    async def get_for_review(
        self, actor: PlatformActor, course_id: str, version: str
    ) -> PackageVersion:
        actor.require(Permission.PACKAGES_REVIEW)

        async def read(tx: PackageTx) -> PackageVersion:
            v = await tx.versions.get(course_id, version)
            if v is None or v.status is PackageStatus.DRAFT:
                raise _not_found()
            return v

        return await self._uow.transaction(read)

    async def approve(
        self, actor: PlatformActor, course_id: str, version: str, inp: ApproveInput, cmd: CommandKey
    ) -> Outcome[PackageVersion]:
        actor.require(Permission.PACKAGES_REVIEW)

        async def write(tx: PackageTx) -> Outcome[PackageVersion]:
            replay = await _replay(tx, actor, cmd)
            if replay is not None:
                return Outcome(
                    value=await _replayed_version(tx, replay), replayed=True, created=False
                )
            v = await self._reviewable(tx, course_id, version)
            if v.status is PackageStatus.SUBMITTED:
                unmet = self._unmet_requirements(v, inp)
                if unmet:
                    raise DomainError(
                        ErrorCode.REVIEW_REQUIREMENTS_NOT_MET, "Cannot approve: " + "; ".join(unmet)
                    )
            now = self._clock.now()
            v = _transition(v, PackageStatus.APPROVED, actor.actor_id, now, inp.notes)
            v = replace(
                v,
                review=ReviewDecision(
                    reviewer_id=actor.actor_id,
                    decision=PackageStatus.APPROVED,
                    decided_at=now,
                    notes=inp.notes,
                    license_attested=inp.license_attested,
                    model_evaluation_attested=inp.model_evaluation_attested,
                ),
            )
            tx.versions.save(v)
            _remember(tx, actor, cmd, v, 200, now)
            return Outcome(value=v, created=False)

        return await self._uow.transaction(write)

    @staticmethod
    def _unmet_requirements(v: PackageVersion, inp: ApproveInput) -> list[str]:
        unmet: list[str] = []
        if not v.report.valid:
            unmet.append("the validator report has errors")
        ev = v.report.evaluation
        if not ev.auto_all_passed:
            unmet.append("evaluation cases failed: " + ", ".join(ev.failures))
        if ev.auto_cases + ev.model_cases == 0:
            unmet.append("the evaluation set is empty")
        if not inp.license_attested:
            unmet.append("the content license must be attested")
        if ev.model_cases and not inp.model_evaluation_attested:
            unmet.append(f"{ev.model_cases} model-graded evaluation case(s) must be attested")
        return unmet

    async def reject(
        self, actor: PlatformActor, course_id: str, version: str, notes: str, cmd: CommandKey
    ) -> Outcome[PackageVersion]:
        actor.require(Permission.PACKAGES_REVIEW)

        async def write(tx: PackageTx) -> Outcome[PackageVersion]:
            replay = await _replay(tx, actor, cmd)
            if replay is not None:
                return Outcome(
                    value=await _replayed_version(tx, replay), replayed=True, created=False
                )
            v = await self._reviewable(tx, course_id, version)
            now = self._clock.now()
            v = _transition(v, PackageStatus.REJECTED, actor.actor_id, now, notes)
            v = replace(
                v,
                review=ReviewDecision(
                    reviewer_id=actor.actor_id, decision=PackageStatus.REJECTED,
                    decided_at=now, notes=notes,
                ),
            )  # fmt: skip
            tx.versions.save(v)
            _remember(tx, actor, cmd, v, 200, now)
            return Outcome(value=v, created=False)

        return await self._uow.transaction(write)

    async def publication_queue(self, actor: PlatformActor) -> Sequence[PackageVersion]:
        """Reviewed versions only; no private drafts or student data."""
        actor.require(Permission.PACKAGES_PUBLISH)

        async def read(tx: PackageTx) -> Sequence[PackageVersion]:
            return await tx.versions.list_by_status(
                (
                    PackageStatus.APPROVED,
                    PackageStatus.ACTIVE,
                    PackageStatus.SUPERSEDED,
                    PackageStatus.RETIRED,
                )
            )

        return await self._uow.transaction(read)

    async def activate(
        self, actor: PlatformActor, course_id: str, version: str, cmd: CommandKey
    ) -> Outcome[PackageVersion]:
        """Make an approved version the one new sessions use. The previous active version
        becomes `superseded` and keeps serving the sessions pinned to it."""
        actor.require(Permission.PACKAGES_PUBLISH)

        async def write(tx: PackageTx) -> Outcome[PackageVersion]:
            replay = await _replay(tx, actor, cmd)
            if replay is not None:
                return Outcome(
                    value=await _replayed_version(tx, replay), replayed=True, created=False
                )
            v = await self._reviewable(tx, course_id, version)
            course = await tx.courses.get(course_id)
            if course is None:  # pragma: no cover - created with the first upload
                raise _not_found()
            now = self._clock.now()
            if course.active_version is not None and course.active_version != version:
                previous = await tx.versions.get(course_id, course.active_version)
                if previous is not None and previous.status is PackageStatus.ACTIVE:
                    if semver_key(previous.version) > semver_key(version):
                        raise DomainError(
                            ErrorCode.INVALID_STATE_TRANSITION,
                            f"{previous.version} is active; an older version cannot replace it.",
                        )
                    tx.versions.save(
                        _transition(
                            previous,
                            PackageStatus.SUPERSEDED,
                            actor.actor_id,
                            now,
                            f"superseded by {version}",
                        )
                    )
            v = _transition(v, PackageStatus.ACTIVE, actor.actor_id, now)
            tx.versions.save(v)
            tx.courses.save(
                replace(course, state=CourseState.ACTIVE, active_version=version, updated_at=now)
            )
            _remember(tx, actor, cmd, v, 200, now)
            return Outcome(value=v, created=False)

        outcome = await self._uow.transaction(write)
        await self._activation.refresh()
        return outcome

    async def retire(
        self, actor: PlatformActor, course_id: str, notes: str, cmd: CommandKey
    ) -> Outcome[PackageVersion]:
        """Stop new enrollments, sessions and commands for a course. Nothing a student did
        is deleted; pinned versions stay loadable for reading past work."""
        actor.require(Permission.PACKAGES_PUBLISH)

        async def write(tx: PackageTx) -> Outcome[PackageVersion]:
            replay = await _replay(tx, actor, cmd)
            if replay is not None:
                return Outcome(
                    value=await _replayed_version(tx, replay), replayed=True, created=False
                )
            course = await tx.courses.get(course_id)
            if course is None or course.active_version is None:
                raise DomainError(ErrorCode.NOT_FOUND, "No active course with this id.")
            v = await tx.versions.get(course_id, course.active_version)
            if v is None:  # pragma: no cover
                raise _not_found()
            now = self._clock.now()
            v = _transition(v, PackageStatus.RETIRED, actor.actor_id, now, notes)
            tx.versions.save(v)
            tx.courses.save(replace(course, state=CourseState.RETIRED, updated_at=now))
            _remember(tx, actor, cmd, v, 200, now)
            return Outcome(value=v, created=False)

        outcome = await self._uow.transaction(write)
        await self._activation.refresh()
        return outcome

    @staticmethod
    async def _reviewable(tx: PackageTx, course_id: str, version: str) -> PackageVersion:
        v = await tx.versions.get(course_id, version)
        if v is None or v.status is PackageStatus.DRAFT:
            raise _not_found()
        return v
