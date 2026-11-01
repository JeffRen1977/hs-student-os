"""Evidence-aware incremental planning (Step 25, BACKEND.md §9). Rules: planner-rules-v1.

Ranking, high → low:
1. deadline — the task has a due date;
2. evidence gap — practice on a skill with little independent evidence (only when the
   student has any assessed work at all);
3. practice — everything else.

Tasks from all enrolled courses share one weekly budget; ranking never uses evidence from
one course to judge another course's task.

Placement over the next seven local days, within `weeklyAvailableMinutes / 7` per day:
in-progress, completed and student-locked tasks are fixed and use their day's budget
first; then each movable task, in rank order, keeps its day if it still has room, else
moves to the earliest day with room (never after its due date), else is deferred past the
horizon. A deadline that cannot fit is placed anyway and flagged over budget. Every entry
carries a student-facing explanation and the event ids its task came from.

Planning never creates tasks and never runs a model. With no assessed work it plans
conservatively: nothing is ranked as a weakness. GET /api/tasks never replans.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.domain.commands import CommandKey, Outcome, find_replay, remember
from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.content import SubjectPackRegistry
from app.domain.ports.repositories import EventDraft, TaskQuery, Tx, UnitOfWork
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.runs import enqueue_run
from app.domain.types.actor import ActorContext, Permission
from app.domain.types.common import PageRequest
from app.domain.types.course import EnrollmentStatus
from app.domain.types.event import EventType
from app.domain.types.plan import (
    HORIZON_DAYS,
    PLANNER_RULE_VERSION,
    PRIORITY_ORDER,
    Placement,
    Plan,
    PlanEntry,
    PlanPriority,
)
from app.domain.types.run import Run, RunKind, RunStatus
from app.domain.types.student import MasteryLevel, Student
from app.domain.types.task import Task, TaskStatus

RUN_RESOURCE = "run"
LOW_EVIDENCE = frozenset({MasteryLevel.INSUFFICIENT_EVIDENCE, MasteryLevel.EMERGING})


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanningInput:
    today: date
    weekly_minutes: int
    tasks: Sequence[Task]
    question_skills: Mapping[str, Sequence[str]]  # questionId → skill ids
    skill_levels: Mapping[str, MasteryLevel]
    skill_names: Mapping[str, str]
    evidence_available: bool

    @property
    def daily_minutes(self) -> int:
        return max(1, math.ceil(self.weekly_minutes / 7))

    @property
    def horizon(self) -> list[date]:
        return [self.today + timedelta(days=i) for i in range(HORIZON_DAYS)]


def rank(task: Task, inp: PlanningInput) -> tuple[PlanPriority, str]:
    if task.due_date is not None:
        return PlanPriority.DEADLINE, f"Due {task.due_date.isoformat()}."
    if inp.evidence_available and task.question_id is not None:
        low = [
            s
            for s in inp.question_skills.get(task.question_id, ())
            if inp.skill_levels.get(s, MasteryLevel.INSUFFICIENT_EVIDENCE) in LOW_EVIDENCE
        ]
        if low:
            names = ", ".join(inp.skill_names.get(s, s) for s in low)
            return PlanPriority.EVIDENCE_GAP, f"Little independent evidence yet for {names}."
    if not inp.evidence_available:
        return PlanPriority.PRACTICE, "Practice. No assessed work yet, so nothing is ranked."
    return PlanPriority.PRACTICE, "Practice."


def _fixed_reason(task: Task) -> str:
    if task.status is TaskStatus.IN_PROGRESS:
        return "In progress; not moved."
    if task.status is TaskStatus.COMPLETED:
        return "Completed."
    return "You set this date; not moved."


def build_plan(inp: PlanningInput) -> list[PlanEntry]:
    horizon = inp.horizon
    end = horizon[-1]
    daily = inp.daily_minutes
    used = dict.fromkeys(horizon, 0)
    entries: list[PlanEntry] = []

    def is_fixed(t: Task) -> bool:
        return t.status in (TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED) or (
            t.status is TaskStatus.PLANNED and t.student_locked
        )

    for t in sorted(inp.tasks, key=lambda t: (t.scheduled_date, t.task_id)):
        if t.status is TaskStatus.SKIPPED or not is_fixed(t):
            continue
        if t.scheduled_date in used:
            used[t.scheduled_date] += t.duration_min
            entries.append(
                PlanEntry(
                    task_id=t.task_id,
                    course_id=t.course_id,
                    duration_min=t.duration_min,
                    previous_date=t.scheduled_date,
                    scheduled_date=t.scheduled_date,
                    priority=None,
                    placement=Placement.FIXED,
                    explanation=_fixed_reason(t),
                    source_event_ids=tuple(t.reason.source_event_ids),
                )
            )

    movable = [t for t in inp.tasks if t.status is TaskStatus.PLANNED and not t.student_locked]
    ranked = [(t, *rank(t, inp)) for t in movable]
    ranked.sort(
        key=lambda x: (
            PRIORITY_ORDER.index(x[1]),
            x[0].due_date or date.max,
            x[0].scheduled_date,
            x[0].task_id,
        )
    )
    for t, priority, why in ranked:
        latest = min(end, t.due_date) if t.due_date else end
        days = [d for d in horizon if d <= latest]
        fits = [d for d in days if used[d] + t.duration_min <= daily]
        if t.scheduled_date in fits:
            day, placement = t.scheduled_date, Placement.KEPT
            where = f"Kept on {day.isoformat()}: fits your {daily}-minute daily budget."
        elif fits:
            day, placement = fits[0], Placement.MOVED
            where = (
                f"Moved from {t.scheduled_date.isoformat()} to {day.isoformat()}, "
                "the earliest day with room."
            )
        elif t.due_date is not None:
            day = max(inp.today, min(t.due_date, end))
            placement = Placement.OVER_BUDGET
            where = f"Placed on {day.isoformat()} for its due date, over the daily budget."
        else:
            day = t.scheduled_date if t.scheduled_date > end else end + timedelta(days=1)
            placement = Placement.DEFERRED
            where = (
                f"Deferred to {day.isoformat()}: this week's "
                f"{inp.weekly_minutes} minutes are already planned."
            )
        if day in used:
            used[day] += t.duration_min
        entries.append(
            PlanEntry(
                task_id=t.task_id,
                course_id=t.course_id,
                duration_min=t.duration_min,
                previous_date=t.scheduled_date,
                scheduled_date=day,
                priority=priority,
                placement=placement,
                explanation=f"{why} {where}",
                source_event_ids=tuple(t.reason.source_event_ids),
            )
        )
    return entries


@dataclass(frozen=True, slots=True, kw_only=True)
class NewTaskPlacement:
    scheduled_date: date
    explanation: str


def place_new_task(
    today: date, weekly_minutes: int, tasks: Sequence[Task], duration_min: int
) -> NewTaskPlacement:
    """Where a consumer-created task goes: the earliest day this week with room after
    every already-scheduled task, else deferred to next week. Nothing else moves."""
    inp = PlanningInput(
        today=today,
        weekly_minutes=weekly_minutes,
        tasks=(),
        question_skills={},
        skill_levels={},
        skill_names={},
        evidence_available=False,
    )
    used = dict.fromkeys(inp.horizon, 0)
    for t in tasks:
        if t.status is not TaskStatus.SKIPPED and t.scheduled_date in used:
            used[t.scheduled_date] += t.duration_min
    for day in inp.horizon:
        if used[day] + duration_min <= inp.daily_minutes:
            return NewTaskPlacement(
                scheduled_date=day, explanation=f"Scheduled for {day.isoformat()}."
            )
    day = inp.horizon[-1] + timedelta(days=1)
    return NewTaskPlacement(
        scheduled_date=day,
        explanation=f"This week's {weekly_minutes} minutes are full, so it starts {day}.",
    )


def local_today(clock_now: datetime, timezone: str) -> date:
    return clock_now.astimezone(ZoneInfo(timezone)).date()


async def all_tasks(
    tx: Tx, actor: ActorContext, course_ids: Sequence[str] | None = None
) -> list[Task]:
    tasks: list[Task] = []
    page = PageRequest(limit=100)
    while True:
        batch = await tx.tasks.list(actor, TaskQuery(course_ids=course_ids), page)
        tasks.extend(batch.items)
        if batch.next_cursor is None:
            return tasks
        page = PageRequest(cursor=batch.next_cursor, limit=100)


class PlannerService:
    def __init__(
        self, uow: UnitOfWork, packs: SubjectPackRegistry, clock: Clock, ids: IdFactory
    ) -> None:
        self._uow = uow
        self._packs = packs
        self._clock = clock
        self._ids = ids

    # ---- Command ----------------------------------------------------------------------

    async def request_replan(self, actor: ActorContext, cmd: CommandKey) -> Outcome[Run]:
        """Queue one PLANNING run (student-scoped, no session). At most one at a time."""
        actor.require(Permission.LEARNING_COMMAND)

        async def write(tx: Tx) -> Outcome[Run]:
            replay = await find_replay(tx, actor, cmd)
            if replay is not None:
                run = await tx.runs.get(actor, replay.resource_id)
                if run is None:  # pragma: no cover - written atomically
                    raise DomainError(ErrorCode.NOT_FOUND, "Run not found.")
                return Outcome(value=run, replayed=True, created=False)
            if await tx.students.get(actor) is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Student not found.")
            state = await tx.plans.get_state(actor)
            if state.active_run_id is not None:
                active = await tx.runs.get(actor, state.active_run_id)
                if active is not None and not active.is_terminal:
                    raise DomainError(ErrorCode.RUN_IN_PROGRESS, "A replan is already running.")
            now = self._clock.now()
            run = Run(
                run_id=self._ids.new("run"),
                student_id=actor.student_id,
                session_id=None,
                status=RunStatus.QUEUED,
                kind=RunKind.PLANNING,
                created_at=now,
                updated_at=now,
            )
            entry = await enqueue_run(
                tx, actor, run, now=now, ids=self._ids, causation_id=run.run_id
            )
            tx.plans.save_state(
                actor,
                dataclasses.replace(state, active_run_id=run.run_id, version=state.version + 1),
            )
            remember(
                tx, actor, cmd, resource_type=RUN_RESOURCE,
                resource_id=run.run_id, response_status=202, now=now,
            )  # fmt: skip
            return Outcome(value=run, delivery_id=entry.delivery_id)

        return await self._uow.transaction(write)

    # ---- Worker (inside the PLANNING run's commit transaction) -------------------------

    async def planning_input(self, tx: Tx, actor: ActorContext, student: Student) -> PlanningInput:
        enrolled = sorted(
            e.course_id for e in await tx.enrollments.list(actor, status=EnrollmentStatus.ACTIVE)
        )
        tasks = await all_tasks(tx, actor, enrolled)
        question_skills: dict[str, Sequence[str]] = {}
        names: dict[str, str] = {}
        for course_id in enrolled:
            pack = self._packs.pack(course_id)
            if pack is not None:
                names.update(pack.skill_names)
        for t in tasks:
            if t.question_id and t.question_id not in question_skills:
                q = self._packs.question(t.course_id, t.question_id)
                question_skills[t.question_id] = tuple(q.skill_ids) if q else ()
        prefixes = tuple(c + "." for c in enrolled)
        levels = {k: v.level for k, v in student.mastery_summary.items() if k.startswith(prefixes)}
        return PlanningInput(
            today=local_today(self._clock.now(), student.preferences.timezone),
            weekly_minutes=student.preferences.weekly_available_minutes,
            tasks=tasks,
            question_skills=question_skills,
            skill_levels=levels,
            skill_names=names,
            evidence_available=bool(levels),
        )

    async def replan_in_tx(self, tx: Tx, actor: ActorContext, run: Run, now: datetime) -> Plan:
        student = await tx.students.get(actor)
        if student is None:
            raise DomainError(ErrorCode.NOT_FOUND, "Student not found.")
        inp = await self.planning_input(tx, actor, student)
        entries = build_plan(inp)
        by_id = {t.task_id: t for t in inp.tasks}
        for e in entries:
            if e.previous_date != e.scheduled_date:
                task = by_id[e.task_id]
                tx.tasks.save(
                    actor,
                    dataclasses.replace(
                        task, scheduled_date=e.scheduled_date, version=task.version + 1
                    ),
                    now=now,
                )
        plan = Plan(
            plan_id=self._ids.new("plan"),
            student_id=actor.student_id,
            run_id=run.run_id,
            rule_version=PLANNER_RULE_VERSION,
            local_date=inp.today,
            horizon_end=inp.horizon[-1],
            weekly_minutes=inp.weekly_minutes,
            daily_minutes=inp.daily_minutes,
            evidence_available=inp.evidence_available,
            entries=tuple(entries),
            created_at=now,
        )
        tx.plans.save(actor, plan)
        state = await tx.plans.get_state(actor)
        tx.plans.save_state(
            actor,
            dataclasses.replace(state, latest_plan_id=plan.plan_id, version=state.version + 1),
        )
        await tx.events.append(
            actor,
            EventDraft(
                type=EventType.PLAN_UPDATED,
                causation_id=run.run_id,
                run_id=run.run_id,
                payload={
                    "planId": plan.plan_id,
                    "changedTaskIds": plan.changed_task_ids,
                    "reason": "replan",
                },
            ),
            event_id=self._ids.new("evt"),
            now=now,
        )
        return plan

    # ---- Reads ------------------------------------------------------------------------

    async def latest_plan(self, actor: ActorContext) -> Plan:
        actor.require(Permission.LEARNING_READ)

        async def read(tx: Tx) -> Plan:
            state = await tx.plans.get_state(actor)
            plan = await tx.plans.get(actor, state.latest_plan_id) if state.latest_plan_id else None
            if plan is None:
                raise DomainError(ErrorCode.NOT_FOUND, "No plan yet.")
            return plan

        return await self._uow.transaction(read)

    async def get_plan(self, actor: ActorContext, plan_id: str) -> Plan:
        actor.require(Permission.LEARNING_READ)

        async def read(tx: Tx) -> Plan:
            plan = await tx.plans.get(actor, plan_id)
            if plan is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Plan not found.")
            return plan

        return await self._uow.transaction(read)
