"""Course access administration (Step 42, API.md §6.5.6, BACKEND.md §2).

Platform admins grant and revoke one student's access to one course, with a reason. Each
change writes, in one transaction: the access record (`access/current`), an audit entry
(`accessAudit/{id}`: who, when, course, grant or revoke, reason), a student event
`access.changed` (course and direction only; never the admin or the reason) and the
idempotency record. A change that changes nothing writes nothing.

The admin is a `PlatformActor` with no student. After checking `entitlements:manage`, this
service builds `ActorContext.for_admin` for exactly one student: it carries no learning
permission, so it reaches the access record and audit, never answers, chats or mastery.

Revoking removes no records: enrollments, tasks, sessions, assessments and mastery stay
readable, and the existing access checks refuse new enrollments, sessions and submissions
(`COURSE_ACCESS_REQUIRED`), and a queued Run re-checks access when it executes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.domain.commands import CommandKey, Outcome, find_replay, remember
from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.catalog import CourseCatalog
from app.domain.ports.repositories import EventDraft, Tx, UnitOfWork
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.types.access import AccessAuditEntry, AccessChange, AccessRecord
from app.domain.types.actor import ActorContext, Permission, PlatformActor
from app.domain.types.course import CourseCategory, CourseDefinition, CourseEnrollment
from app.domain.types.event import EventType
from app.domain.types.student import Entitlements

ACCESS_RESOURCE = "access_change"
UNCHANGED = "unchanged"  # idempotency resource id for a change that changed nothing
AUDIT_LIMIT = 50
MAX_BULK = 200


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseAccess:
    course: CourseDefinition
    granted: bool
    enrollment: CourseEnrollment | None


@dataclass(frozen=True, slots=True, kw_only=True)
class StudentAccess:
    student_id: str
    display_name: str
    access: AccessRecord
    courses: Sequence[CourseAccess]
    audit: Sequence[AccessAuditEntry]


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessChangeResult:
    changed: bool
    audit_id: str | None
    access: StudentAccess


@dataclass(frozen=True, slots=True, kw_only=True)
class BulkResult:
    student_id: str
    status: str  # "changed" | "unchanged" | "failed"
    audit_id: str | None = None
    error_code: str | None = None
    message: str | None = None


def _without(ids: Sequence[str], course_id: str) -> tuple[str, ...]:
    return tuple(c for c in ids if c != course_id)


def apply_change(
    current: Entitlements, course: CourseDefinition | None, course_id: str, change: AccessChange
) -> Entitlements:
    """The entitlements after the change. AP courses are kept in `ap_courses`, every other
    course in `courses` (a storage location only: either list grants access)."""
    if change is AccessChange.REVOKE:
        return replace(
            current,
            ap_courses=_without(current.ap_courses, course_id),
            courses=_without(current.courses, course_id),
        )
    if current.grants(course_id):
        return current
    if course is not None and course.category is CourseCategory.AP:
        return replace(current, ap_courses=(*current.ap_courses, course_id))
    return replace(current, courses=(*current.courses, course_id))


class AccessService:
    def __init__(
        self, uow: UnitOfWork, catalog: CourseCatalog, clock: Clock, ids: IdFactory
    ) -> None:
        self._uow = uow
        self._catalog = catalog
        self._clock = clock
        self._ids = ids

    @staticmethod
    def _for_student(admin: PlatformActor, student_id: str) -> ActorContext:
        admin.require(Permission.ENTITLEMENTS_MANAGE)
        try:
            return ActorContext.for_admin(admin.actor_id, student_id, admin.request_id)
        except ValueError as exc:  # e.g. an admin uid equal to the student id
            raise DomainError(ErrorCode.NOT_FOUND, "Student not found.") from exc

    async def _view(self, tx: Tx, actor: ActorContext) -> StudentAccess:
        student = await tx.students.get(actor)
        if student is None:
            raise DomainError(ErrorCode.NOT_FOUND, "Student not found.")
        record = await tx.students.get_access(actor)
        enrollments = {e.course_id: e for e in await tx.enrollments.list(actor)}
        courses = [
            CourseAccess(
                course=c,
                granted=record.entitlements.grants(c.course_id),
                enrollment=enrollments.get(c.course_id),
            )
            for c in sorted(self._catalog.list(), key=lambda c: c.course_id)
        ]
        return StudentAccess(
            student_id=actor.student_id,
            display_name=student.profile.display_name,
            access=record,
            courses=courses,
            audit=await tx.access_audit.list_recent(actor, AUDIT_LIMIT),
        )

    async def view(self, admin: PlatformActor, student_id: str) -> StudentAccess:
        actor = self._for_student(admin, student_id)

        async def read(tx: Tx) -> StudentAccess:
            return await self._view(tx, actor)

        return await self._uow.transaction(read)

    async def change(
        self,
        admin: PlatformActor,
        student_id: str,
        course_id: str,
        change: AccessChange,
        reason: str,
        cmd: CommandKey,
    ) -> Outcome[AccessChangeResult]:
        actor = self._for_student(admin, student_id)
        course = self._catalog.get(course_id)

        async def write(tx: Tx) -> Outcome[AccessChangeResult]:
            replay = await find_replay(tx, actor, cmd)
            if replay is not None:
                audit_id = None if replay.resource_id == UNCHANGED else replay.resource_id
                view = await self._view(tx, actor)
                result = AccessChangeResult(
                    changed=audit_id is not None, audit_id=audit_id, access=view
                )
                return Outcome(value=result, replayed=True, created=False)

            if await tx.students.get(actor) is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Student not found.")
            if change is AccessChange.GRANT and course is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Course not found.")
            now = self._clock.now()
            record = await tx.students.get_access(actor)
            after = apply_change(record.entitlements, course, course_id, change)
            if after == record.entitlements:
                remember(
                    tx, actor, cmd, resource_type=ACCESS_RESOURCE,
                    resource_id=UNCHANGED, response_status=200, now=now,
                )  # fmt: skip
                view = await self._view(tx, actor)
                return Outcome(
                    value=AccessChangeResult(changed=False, audit_id=None, access=view),
                    created=False,
                )

            audit_id = self._ids.new("aud")
            entry = AccessAuditEntry(
                audit_id=audit_id, student_id=student_id, course_id=course_id,
                change=change, reason=reason, actor_id=admin.actor_id, at=now,
            )  # fmt: skip
            tx.students.save_entitlements(actor, after, now=now)
            tx.access_audit.append(actor, entry)
            await tx.events.append(
                actor,
                EventDraft(
                    type=EventType.ACCESS_CHANGED,
                    causation_id=None,
                    payload={
                        "courseId": course_id,
                        "change": "granted" if change is AccessChange.GRANT else "revoked",
                    },
                ),
                event_id=self._ids.new("evt"),
                now=now,
            )
            remember(
                tx, actor, cmd, resource_type=ACCESS_RESOURCE,
                resource_id=audit_id, response_status=200, now=now,
            )  # fmt: skip
            view = await self._view(tx, actor)
            # The queries in _view do not see this transaction's writes: put the new record
            # and audit entry in the view directly.
            view = replace(
                view,
                access=AccessRecord(entitlements=after, updated_at=now, updated_by=admin.actor_id),
                courses=[
                    replace(c, granted=after.grants(c.course.course_id)) for c in view.courses
                ],
                audit=[entry, *view.audit][:AUDIT_LIMIT],
            )
            return Outcome(value=AccessChangeResult(changed=True, audit_id=audit_id, access=view))

        return await self._uow.transaction(write)

    async def bulk(
        self,
        admin: PlatformActor,
        student_ids: Sequence[str],
        course_id: str,
        change: AccessChange,
        reason: str,
        cmd: CommandKey,
    ) -> list[BulkResult]:
        """One transaction and one audit entry per student; a failure for one student
        never affects another. A retry with the same key replays the students that
        succeeded and retries the ones that failed."""
        admin.require(Permission.ENTITLEMENTS_MANAGE)
        results: list[BulkResult] = []
        for sid in dict.fromkeys(student_ids):  # de-duplicated, order kept
            sub = CommandKey(
                scope=cmd.scope,
                key=hashlib.sha256(f"{cmd.key}\n{sid}".encode()).hexdigest(),
                request_digest=cmd.request_digest,
            )
            try:
                out = await self.change(admin, sid, course_id, change, reason, sub)
            except DomainError as exc:
                if exc.code is ErrorCode.FORBIDDEN:
                    raise
                failed = BulkResult(
                    student_id=sid, status="failed", error_code=exc.code.value, message=exc.message
                )
                results.append(failed)
                continue
            value = out.value
            results.append(
                BulkResult(
                    student_id=sid,
                    status="changed" if value.changed else "unchanged",
                    audit_id=value.audit_id,
                )
            )
        return results
