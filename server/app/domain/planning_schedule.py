"""Timezone-aware daily planning (Step 28, BACKEND.md §8).

Every student with an active schedule gets one scheduled planning pass per *local* day, at
`PlanningSchedulePolicy.local_time` (04:00 by default) in their IANA timezone. The pass is
an ordinary PLANNING run (same planner as a student-requested replan, Step 28.3); this
module only decides *whether* to queue one.

Rules, all decided inside one transaction on `planState/current`:

- **Due**: `nextDueAt <= now`. Re-checked in the transaction, so two scheduler invocations
  that both saw the student as due cannot both act.
- **Dedupe**: `studentId + localDate + scheduled`. `lastScheduledLocalDate` records the
  local date already covered, and the run id is derived from it, so even a lost state
  write cannot queue a second scheduled run for the same day.
- **Catch-up**: after downtime the student gets one pass for *today* (not one per missed
  day), and `nextDueAt` jumps to tomorrow's slot.
- **Overlap**: if a PLANNING run is already queued or running (a student replan), it will
  plan today with the current state, so the scheduled pass coalesces into it.
- **DST / timezone change**: slots are computed with `app.domain.local_time`; a timezone
  change recomputes `nextDueAt` in the new zone (`reset_schedule`).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum

from app.domain.local_time import at_local, local_date, next_at_local
from app.domain.ports.repositories import Tx
from app.domain.ports.runtime import IdFactory
from app.domain.runs import enqueue_run
from app.domain.types.actor import ActorContext
from app.domain.types.course import EnrollmentStatus
from app.domain.types.plan import PlanState, PlanTrigger
from app.domain.types.run import Run, RunKind, RunStatus

DEFAULT_PLANNING_TIME = time(4, 0)


@dataclass(frozen=True, slots=True)
class PlanningSchedulePolicy:
    local_time: time = DEFAULT_PLANNING_TIME

    def first_due(self, now: datetime, timezone: str) -> datetime:
        """The next slot strictly after `now`."""
        return next_at_local(now, self.local_time, timezone)

    def due_after(self, day: date, timezone: str) -> datetime:
        """The slot on the local day after `day` (the day just planned)."""
        return at_local(day + timedelta(days=1), self.local_time, timezone)


class ScheduleOutcome(StrEnum):
    QUEUED = "queued"  # a scheduled PLANNING run was queued
    COALESCED = "coalesced"  # an in-flight replan covers today
    ALREADY_PLANNED = "already_planned"  # this local date already had its scheduled pass
    NOTHING_TO_PLAN = "nothing_to_plan"  # no active enrollment: just advance
    NOT_DUE = "not_due"  # moved on since the scan (duplicate invocation, reset)


def scheduled_run_id(student_id: str, day: date) -> str:
    """Deterministic per student and local date. It includes the student id because the
    delivery id derived from it names the Cloud Tasks task, and task names are unique per
    queue, not per student."""
    return f"run_sched_{day.strftime('%Y%m%d')}_{student_id}"


async def ensure_schedule(
    tx: Tx,
    actor: ActorContext,
    policy: PlanningSchedulePolicy,
    timezone: str,
    now: datetime,
    *,
    reset: bool = False,
) -> None:
    """Start the schedule (first enrollment) or recompute it for a new timezone."""
    state = await tx.plans.get_state(actor)
    if state.next_due_at is not None and not reset:
        return
    if reset and state.next_due_at is not None and state.timezone == timezone:
        return
    tx.plans.save_state(
        actor,
        dataclasses.replace(
            state,
            next_due_at=policy.first_due(now, timezone),
            timezone=timezone,
            version=state.version + 1,
        ),
    )


async def schedule_due_planning(
    tx: Tx,
    actor: ActorContext,
    policy: PlanningSchedulePolicy,
    *,
    now: datetime,
    ids: IdFactory,
) -> ScheduleOutcome:
    state = await tx.plans.get_state(actor)
    if state.next_due_at is None or state.next_due_at > now:
        return ScheduleOutcome.NOT_DUE
    student = await tx.students.get(actor)
    if student is None:  # deleted student: stop scanning it
        tx.plans.save_state(actor, dataclasses.replace(state, next_due_at=None))
        return ScheduleOutcome.NOTHING_TO_PLAN
    tz = student.preferences.timezone
    today = local_date(now, tz)

    def advanced(s: PlanState, **changes: object) -> PlanState:
        return dataclasses.replace(
            s,
            next_due_at=policy.due_after(today, tz),
            timezone=tz,
            last_scheduled_local_date=today,
            version=s.version + 1,
            **changes,  # type: ignore[arg-type]
        )

    if state.last_scheduled_local_date is not None and state.last_scheduled_local_date >= today:
        tx.plans.save_state(
            actor,
            dataclasses.replace(
                state,
                next_due_at=policy.due_after(state.last_scheduled_local_date, tz),
                timezone=tz,
                version=state.version + 1,
            ),
        )
        return ScheduleOutcome.ALREADY_PLANNED
    if not await tx.enrollments.list(actor, status=EnrollmentStatus.ACTIVE):
        tx.plans.save_state(actor, advanced(state))
        return ScheduleOutcome.NOTHING_TO_PLAN
    if state.active_run_id is not None:
        active = await tx.runs.get(actor, state.active_run_id)
        if active is not None and not active.is_terminal:
            tx.plans.save_state(actor, advanced(state))
            return ScheduleOutcome.COALESCED
    run_id = scheduled_run_id(actor.student_id, today)
    if await tx.runs.get(actor, run_id) is not None:  # belt and braces: per-day run id
        tx.plans.save_state(actor, advanced(state))
        return ScheduleOutcome.ALREADY_PLANNED
    run = Run(
        run_id=run_id,
        student_id=actor.student_id,
        session_id=None,
        status=RunStatus.QUEUED,
        kind=RunKind.PLANNING,
        created_at=now,
        updated_at=now,
    )
    await enqueue_run(tx, actor, run, now=now, ids=ids, causation_id=run_id)
    tx.plans.save_state(
        actor, advanced(state, active_run_id=run_id, active_trigger=PlanTrigger.SCHEDULED)
    )
    return ScheduleOutcome.QUEUED
