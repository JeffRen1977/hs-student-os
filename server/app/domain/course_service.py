"""Course catalog, enrollment, and per-course agent activation (Steps 10–11)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.domain.access import (
    check_available_and_entitled,
    is_enrolled,
    is_entitled,
    require_known_course,
)
from app.domain.commands import CommandKey, Outcome, find_replay, remember
from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.catalog import CourseCatalog
from app.domain.ports.repositories import EventDraft, SessionQuery, Tx, UnitOfWork
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.types.actor import ActorContext, Permission
from app.domain.types.common import PageRequest
from app.domain.types.course import (
    CourseCatalogEntry,
    CourseDefinition,
    CourseEnrollment,
    EnrollmentStatus,
)
from app.domain.types.event import EventType
from app.domain.types.session import Session, SessionStatus
from app.domain.types.student import MasterySummary

ENROLLMENT_RESOURCE = "enrollment"


@dataclass(frozen=True, slots=True, kw_only=True)
class EnrolledCourse:
    course: CourseDefinition
    enrollment: CourseEnrollment


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseAgent:
    course: CourseDefinition
    active_sessions: Sequence[Session]
    mastery_summary: Mapping[str, MasterySummary]


class CourseService:
    def __init__(
        self, uow: UnitOfWork, catalog: CourseCatalog, clock: Clock, ids: IdFactory
    ) -> None:
        self._uow = uow
        self._catalog = catalog
        self._clock = clock
        self._ids = ids

    # ---- Catalog ----------------------------------------------------------------------

    def _entry(
        self, course: CourseDefinition, entitled: bool, enrollment: CourseEnrollment | None
    ) -> CourseCatalogEntry:
        return CourseCatalogEntry(
            course_id=course.course_id,
            name=course.name,
            description=course.description,
            category=course.category,
            availability=course.availability,
            entitled=entitled,
            enrolled=is_enrolled(enrollment),
            agent=course.agent,
        )

    async def catalog(self, actor: ActorContext) -> list[CourseCatalogEntry]:
        actor.require(Permission.LEARNING_READ)

        async def read(tx: Tx) -> list[CourseCatalogEntry]:
            entitlements = await tx.students.get_entitlements(actor)
            enrollments = {e.course_id: e for e in await tx.enrollments.list(actor)}
            return [
                self._entry(c, is_entitled(entitlements, c), enrollments.get(c.course_id))
                for c in self._catalog.list()
            ]

        return await self._uow.transaction(read)

    async def course(self, actor: ActorContext, course_id: str) -> CourseCatalogEntry:
        actor.require(Permission.LEARNING_READ)
        course = require_known_course(self._catalog, course_id)

        async def read(tx: Tx) -> CourseCatalogEntry:
            entitlements = await tx.students.get_entitlements(actor)
            enrollment = await tx.enrollments.get(actor, course_id)
            return self._entry(course, is_entitled(entitlements, course), enrollment)

        return await self._uow.transaction(read)

    # ---- Enrollment -------------------------------------------------------------------

    async def enroll(
        self, actor: ActorContext, course_id: str, cmd: CommandKey
    ) -> Outcome[CourseEnrollment]:
        actor.require(Permission.LEARNING_COMMAND)

        async def write(tx: Tx) -> Outcome[CourseEnrollment]:
            replay = await find_replay(tx, actor, cmd)
            if replay is not None:
                existing = await tx.enrollments.get(actor, replay.resource_id)
                if existing is None:  # pragma: no cover - records outlive nothing here
                    raise DomainError(ErrorCode.NOT_FOUND, "Enrollment not found.")
                return Outcome(value=existing, replayed=True, created=False)

            course = require_known_course(self._catalog, course_id)
            check_available_and_entitled(course, await tx.students.get_entitlements(actor))
            now = self._clock.now()
            current = await tx.enrollments.get(actor, course_id)
            if is_enrolled(current):
                assert current is not None
                remember(
                    tx, actor, cmd, resource_type=ENROLLMENT_RESOURCE,
                    resource_id=course_id, response_status=200, now=now,
                )  # fmt: skip
                return Outcome(value=current, created=False)

            # Re-enrolling reuses the same document; mastery, assessments and history were
            # never deleted, so they are visible again.
            enrollment = CourseEnrollment(
                student_id=actor.student_id,
                course_id=course_id,
                status=EnrollmentStatus.ACTIVE,
                enrolled_at=now,
                unenrolled_at=None,
            )
            tx.enrollments.save(actor, enrollment)
            await tx.events.append(
                actor,
                EventDraft(
                    type=EventType.COURSE_ENROLLED,
                    causation_id=None,
                    payload={"courseId": course_id},
                ),
                event_id=self._ids.new("evt"),
                now=now,
            )
            remember(
                tx, actor, cmd, resource_type=ENROLLMENT_RESOURCE,
                resource_id=course_id, response_status=200, now=now,
            )  # fmt: skip
            return Outcome(value=enrollment)

        return await self._uow.transaction(write)

    async def unenroll(
        self, actor: ActorContext, course_id: str, cmd: CommandKey
    ) -> Outcome[CourseEnrollment]:
        actor.require(Permission.LEARNING_COMMAND)

        async def write(tx: Tx) -> Outcome[CourseEnrollment]:
            replay = await find_replay(tx, actor, cmd)
            if replay is not None:
                existing = await tx.enrollments.get(actor, replay.resource_id)
                if existing is None:  # pragma: no cover
                    raise DomainError(ErrorCode.NOT_FOUND, "Enrollment not found.")
                return Outcome(value=existing, replayed=True, created=False)

            require_known_course(self._catalog, course_id)
            current = await tx.enrollments.get(actor, course_id)
            if current is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Not enrolled in this course.")
            now = self._clock.now()
            if current.status is EnrollmentStatus.UNENROLLED:
                remember(
                    tx, actor, cmd, resource_type=ENROLLMENT_RESOURCE,
                    resource_id=course_id, response_status=200, now=now,
                )  # fmt: skip
                return Outcome(value=current, created=False)

            open_sessions = await tx.sessions.list(
                actor,
                SessionQuery(course_id=course_id, status=SessionStatus.OPEN),
                PageRequest(limit=1),
            )
            if open_sessions.items:
                raise DomainError(
                    ErrorCode.OPEN_SESSION_EXISTS,
                    "Finish or abandon the open session in this course first.",
                )
            updated = CourseEnrollment(
                student_id=actor.student_id,
                course_id=course_id,
                status=EnrollmentStatus.UNENROLLED,
                enrolled_at=current.enrolled_at,
                unenrolled_at=now,
            )
            tx.enrollments.save(actor, updated)
            await tx.events.append(
                actor,
                EventDraft(
                    type=EventType.COURSE_UNENROLLED,
                    causation_id=None,
                    payload={"courseId": course_id},
                ),
                event_id=self._ids.new("evt"),
                now=now,
            )
            remember(
                tx, actor, cmd, resource_type=ENROLLMENT_RESOURCE,
                resource_id=course_id, response_status=200, now=now,
            )  # fmt: skip
            return Outcome(value=updated)

        return await self._uow.transaction(write)

    # ---- Workspace --------------------------------------------------------------------

    async def enrolled(self, actor: ActorContext) -> list[EnrolledCourse]:
        actor.require(Permission.LEARNING_READ)

        async def read(tx: Tx) -> list[EnrolledCourse]:
            result: list[EnrolledCourse] = []
            for enrollment in await tx.enrollments.list(actor, status=EnrollmentStatus.ACTIVE):
                course = self._catalog.get(enrollment.course_id)
                if course is not None:
                    result.append(EnrolledCourse(course=course, enrollment=enrollment))
            return result

        return await self._uow.transaction(read)

    async def agent(self, actor: ActorContext, course_id: str) -> CourseAgent:
        actor.require(Permission.LEARNING_READ)

        async def read(tx: Tx) -> CourseAgent:
            course = self._catalog.get(course_id)
            if course is None or not is_enrolled(await tx.enrollments.get(actor, course_id)):
                # Same 404 for unknown and not-enrolled: the agent only exists once enrolled.
                raise DomainError(ErrorCode.NOT_FOUND, "Not enrolled in this course.")
            sessions = await tx.sessions.list(
                actor,
                SessionQuery(course_id=course_id, status=SessionStatus.OPEN),
                PageRequest(limit=10),
            )
            student = await tx.students.get(actor)
            prefix = course_id + "."
            mastery = (
                {k: v for k, v in student.mastery_summary.items() if k.startswith(prefix)}
                if student
                else {}
            )
            return CourseAgent(
                course=course, active_sessions=sessions.items, mastery_summary=mastery
            )

        return await self._uow.transaction(read)
