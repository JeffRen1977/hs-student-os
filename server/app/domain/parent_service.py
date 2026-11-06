"""Scoped parent summaries (Step 36).

    student ──invite(scopes)──► pending link + one-time code (shown once, stored hashed)
    parent  ──accept(code)────► active link (student side) + the parent's index entry
    student ──revoke──────────► revoked link; the parent's index entry is removed
    parent  ──summary─────────► re-checks the link and scope *in the same transaction*

A parent never holds a student-scoped actor outside a transaction that has just verified
an active link. Unknown, foreign, revoked or expired links all read as 404, so a parent
cannot probe which student ids exist. The summary is a projection built here field by
field: it never includes messages, submissions, assessment feedback, essays or
admissions data.
"""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import timedelta

from app.domain.commands import CommandKey, Outcome, find_replay, remember
from app.domain.errors import DomainError, ErrorCode
from app.domain.local_time import local_date
from app.domain.ports.catalog import CourseCatalog
from app.domain.ports.repositories import TaskQuery, Tx, UnitOfWork
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.types.actor import ActorContext, ParentActor, Permission
from app.domain.types.common import IdempotencyRecord, PageRequest
from app.domain.types.course import EnrollmentStatus
from app.domain.types.parent import (
    INVITE_TTL_DAYS,
    CourseProgress,
    ParentChild,
    ParentInvite,
    ParentLink,
    ParentLinkStatus,
    ParentSummary,
    SkillProgress,
    UpcomingTask,
    WeekSummary,
)
from app.domain.types.task import TaskStatus

LINK_RESOURCE = "parent_link"
MAX_ACTIVE_LINKS = 4
UPCOMING_LIMIT = 10
TASK_PAGE = 100


def code_hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def _not_found() -> DomainError:
    return DomainError(ErrorCode.NOT_FOUND, "Not found.")


@dataclasses.dataclass(frozen=True, slots=True, kw_only=True)
class CreatedInvite:
    link: ParentLink
    code: str  # returned once, to the student; only its hash is stored


class ParentService:
    def __init__(
        self, uow: UnitOfWork, catalog: CourseCatalog, clock: Clock, ids: IdFactory
    ) -> None:
        self._uow = uow
        self._catalog = catalog
        self._clock = clock
        self._ids = ids

    def _new_code(self) -> str:
        # The id factory's random part (80 bits in production). Shown to the student once.
        return self._ids.new("pinv").split("_", 1)[1].upper()

    # ---- Student side --------------------------------------------------------------------

    async def invite(
        self, actor: ActorContext, scopes: frozenset[Permission], cmd: CommandKey
    ) -> Outcome[CreatedInvite]:
        actor.require(Permission.TWIN_WRITE)
        if not scopes or not scopes <= {Permission.SUMMARY_READ}:
            raise DomainError(ErrorCode.VALIDATION_FAILED, "Only summary:read can be shared.")

        async def body(tx: Tx) -> Outcome[CreatedInvite]:
            now = self._clock.now()
            record = await find_replay(tx, actor, cmd)
            if record is not None:
                # The code is never stored in clear, so a replay cannot show it again.
                link = await tx.parents.get_link(actor, record.resource_id)
                if link is None:  # pragma: no cover - links are never deleted
                    raise _not_found()
                return Outcome(value=CreatedInvite(link=link, code=""), replayed=True)
            live = [
                link
                for link in await tx.parents.list_links(actor)
                if link.status in (ParentLinkStatus.PENDING, ParentLinkStatus.ACTIVE)
            ]
            if len(live) >= MAX_ACTIVE_LINKS:
                raise DomainError(
                    ErrorCode.PARENT_LINK_LIMIT,
                    "Revoke an existing parent link before adding another.",
                )
            code = self._new_code()
            link = ParentLink(
                link_id=self._ids.new("plink"),
                student_id=actor.student_id,
                status=ParentLinkStatus.PENDING,
                scopes=tuple(sorted(s.value for s in scopes)),
                invite_code_hash=code_hash(code),
                invite_expires_at=now + timedelta(days=INVITE_TTL_DAYS),
                created_at=now,
            )
            tx.parents.save_link(actor, link)
            tx.parents.save_invite(
                ParentInvite(
                    code_hash=link.invite_code_hash,
                    student_id=actor.student_id,
                    link_id=link.link_id,
                    expires_at=link.invite_expires_at,
                )
            )
            remember(tx, actor, cmd, resource_type=LINK_RESOURCE, resource_id=link.link_id,
                     response_status=201, now=now)  # fmt: skip
            return Outcome(value=CreatedInvite(link=link, code=code))

        return await self._uow.transaction(body)

    async def list_links(self, actor: ActorContext) -> list[ParentLink]:
        actor.require(Permission.TWIN_READ)

        async def body(tx: Tx) -> list[ParentLink]:
            return [self._expire(link) for link in await tx.parents.list_links(actor)]

        return await self._uow.transaction(body)

    async def revoke(
        self, actor: ActorContext, link_id: str, cmd: CommandKey
    ) -> Outcome[ParentLink]:
        actor.require(Permission.TWIN_WRITE)

        async def body(tx: Tx) -> Outcome[ParentLink]:
            now = self._clock.now()
            record = await find_replay(tx, actor, cmd)
            link = await tx.parents.get_link(actor, link_id)
            if link is None:
                raise _not_found()
            if record is not None:
                return Outcome(value=link, replayed=True, created=False)
            if link.status in (ParentLinkStatus.PENDING, ParentLinkStatus.ACTIVE):
                if link.parent_uid is not None:
                    tx.parents.delete_child(link.parent_uid, actor.student_id)
                link = dataclasses.replace(
                    link, status=ParentLinkStatus.REVOKED, revoked_at=now, version=link.version + 1
                )
                tx.parents.save_link(actor, link)
            remember(tx, actor, cmd, resource_type=LINK_RESOURCE, resource_id=link.link_id,
                     response_status=200, now=now)  # fmt: skip
            return Outcome(value=link, created=False)

        return await self._uow.transaction(body)

    def _expire(self, link: ParentLink) -> ParentLink:
        if link.status is ParentLinkStatus.PENDING and link.invite_expires_at <= self._clock.now():
            return dataclasses.replace(link, status=ParentLinkStatus.EXPIRED)
        return link

    # ---- Parent side ---------------------------------------------------------------------

    async def accept(
        self, parent: ParentActor, display_name: str, code: str, cmd: CommandKey
    ) -> Outcome[ParentChild]:
        async def body(tx: Tx) -> Outcome[ParentChild]:
            now = self._clock.now()
            key = cmd.key_hash(parent)
            record = await tx.parents.get_parent_idempotency(parent.actor_id, key)
            if record is not None:
                if record.scope != cmd.scope or record.request_digest != cmd.request_digest:
                    raise DomainError(
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "This Idempotency-Key was already used with a different request.",
                    )
                child = await tx.parents.get_child(parent.actor_id, record.resource_id)
                if child is None:  # revoked since: the replay must not resurrect access
                    raise _not_found()
                return Outcome(value=child, replayed=True)
            invite = await tx.parents.get_invite(code_hash(code))
            if invite is None or invite.redeemed_by is not None or invite.expires_at <= now:
                raise _not_found()  # wrong, used or expired codes look the same
            # Scoped to the one student the invite names, for the link write only.
            student = ActorContext.for_parent(
                parent.actor_id, invite.student_id, frozenset({Permission.SUMMARY_READ})
            )
            link = await tx.parents.get_link(student, invite.link_id)
            if link is None or link.status is not ParentLinkStatus.PENDING:
                raise _not_found()
            if invite.student_id == parent.actor_id:
                raise DomainError(ErrorCode.FORBIDDEN, "A student cannot be their own parent.")
            tx.parents.save_link(
                student,
                dataclasses.replace(
                    link,
                    status=ParentLinkStatus.ACTIVE,
                    parent_uid=parent.actor_id,
                    parent_display_name=display_name,
                    accepted_at=now,
                    version=link.version + 1,
                ),
            )
            tx.parents.save_invite(dataclasses.replace(invite, redeemed_by=parent.actor_id))
            child = ParentChild(student_id=invite.student_id, link_id=link.link_id, created_at=now)
            tx.parents.save_child(parent.actor_id, child)
            tx.parents.save_parent_idempotency(
                parent.actor_id,
                IdempotencyRecord(
                    key_hash=key, scope=cmd.scope, request_digest=cmd.request_digest,
                    resource_type="parent_child", resource_id=invite.student_id,
                    response_status=200, created_at=now,
                ),
            )  # fmt: skip
            return Outcome(value=child)

        return await self._uow.transaction(body)

    async def _verified(
        self, tx: Tx, parent: ParentActor, student_id: str, scope: Permission
    ) -> tuple[ActorContext, ParentLink]:
        """The scoped actor for one linked student, or 404. Called inside every read."""
        child = await tx.parents.get_child(parent.actor_id, student_id)
        if child is None:
            raise _not_found()
        actor = ActorContext.for_parent(
            parent.actor_id, student_id, frozenset({scope}), request_id=parent.request_id
        )
        link = await tx.parents.get_link(actor, child.link_id)
        if (
            link is None
            or not link.is_active_for(parent.actor_id)
            or scope.value not in link.scopes
        ):
            raise _not_found()
        return actor, link

    async def list_students(self, parent: ParentActor) -> list[tuple[ParentChild, str]]:
        """Linked students with an active link: (index entry, display name)."""

        async def body(tx: Tx) -> list[tuple[ParentChild, str]]:
            out: list[tuple[ParentChild, str]] = []
            for child in await tx.parents.list_children(parent.actor_id):
                try:
                    actor, _ = await self._verified(
                        tx, parent, child.student_id, Permission.SUMMARY_READ
                    )
                except DomainError:
                    continue
                student = await tx.students.get(actor)
                if student is not None:
                    out.append((child, student.profile.display_name))
            return out

        return await self._uow.transaction(body)

    async def summary(self, parent: ParentActor, student_id: str) -> ParentSummary:
        async def body(tx: Tx) -> ParentSummary:
            actor, _ = await self._verified(tx, parent, student_id, Permission.SUMMARY_READ)
            actor.require(Permission.SUMMARY_READ)
            student = await tx.students.get(actor)
            if student is None:
                raise _not_found()
            now = self._clock.now()
            today = local_date(now, student.preferences.timezone)
            courses: list[CourseProgress] = []
            for e in await tx.enrollments.list(actor, status=EnrollmentStatus.ACTIVE):
                course = self._catalog.get(e.course_id)
                prefix = e.course_id + "."
                prediction = student.prediction_summary.get(e.course_id)
                courses.append(
                    CourseProgress(
                        course_id=e.course_id,
                        name=course.name if course else e.course_id,
                        skills=tuple(
                            SkillProgress(
                                skill_id=sid,
                                level=m.level,
                                independent_evidence_count=m.independent_evidence_count,
                            )
                            for sid, m in sorted(student.mastery_summary.items())
                            if sid.startswith(prefix)
                        ),
                        prediction_status=prediction.status.value if prediction else "unavailable",
                    )
                )
            week_start = today - timedelta(days=today.weekday())
            week_end = week_start + timedelta(days=6)
            planned = completed = skipped = 0
            upcoming: list[UpcomingTask] = []
            page = PageRequest(limit=TASK_PAGE)
            for _ in range(5):
                batch = await tx.tasks.list(actor, TaskQuery(), page)
                for t in batch.items:
                    if week_start <= t.scheduled_date <= week_end:
                        if t.status is TaskStatus.COMPLETED:
                            completed += 1
                        elif t.status is TaskStatus.SKIPPED:
                            skipped += 1
                        else:
                            planned += 1
                    if (
                        t.status in (TaskStatus.PLANNED, TaskStatus.IN_PROGRESS)
                        and today <= t.scheduled_date <= today + timedelta(days=7)
                        and len(upcoming) < UPCOMING_LIMIT
                    ):
                        upcoming.append(
                            UpcomingTask(
                                course_id=t.course_id, title=t.title,
                                scheduled_date=t.scheduled_date, duration_min=t.duration_min,
                            )
                        )  # fmt: skip
                if batch.next_cursor is None:
                    break
                page = PageRequest(cursor=batch.next_cursor, limit=TASK_PAGE)
            return ParentSummary(
                student_id=student_id,
                display_name=student.profile.display_name,
                grade=student.profile.grade,
                courses=tuple(courses),
                week=WeekSummary(
                    start=week_start,
                    end=week_end,
                    planned=planned,
                    completed=completed,
                    skipped=skipped,
                    upcoming=tuple(upcoming),
                ),
                generated_at=now,
            )

        return await self._uow.transaction(body)
