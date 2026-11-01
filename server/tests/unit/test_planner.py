"""Step 25.4: planner-rules-v1 as a pure function."""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta

from app.domain.planner_service import PlanningInput, build_plan, place_new_task
from app.domain.types.common import TaskType
from app.domain.types.plan import Placement, PlanEntry, PlanPriority
from app.domain.types.student import MasteryLevel
from app.domain.types.task import Task, TaskReason, TaskReasonCode, TaskStatus
from tests.support import make_task

TODAY = date(2026, 11, 2)


def task(
    tid: str,
    *,
    day: date = TODAY,
    minutes: int = 20,
    status: TaskStatus = TaskStatus.PLANNED,
    locked: bool = False,
    due: date | None = None,
    reason: TaskReasonCode = TaskReasonCode.INITIAL_PRACTICE,
    question: str | None = None,
) -> Task:
    return dataclasses.replace(
        make_task("stu_alex", tid, scheduled=day, status=status),
        duration_min=minutes,
        student_locked=locked,
        due_date=due,
        reason=TaskReason(code=reason, source_event_ids=(f"evt_{tid}",)),
        question_id=question,
        task_type=TaskType.FRQ_PRACTICE,
    )


def plan(
    tasks: list[Task], *, weekly: int = 140, evidence: bool = True, **kw: object
) -> dict[str, PlanEntry]:
    inp = PlanningInput(
        today=TODAY,
        weekly_minutes=weekly,
        tasks=tasks,
        question_skills=kw.get("question_skills", {}),  # type: ignore[arg-type]
        skill_levels=kw.get("skill_levels", {}),  # type: ignore[arg-type]
        skill_names={"calc_bc.chain-rule": "Chain rule"},
        evidence_available=evidence,
    )
    return {e.task_id: e for e in build_plan(inp)}


def test_full_schedule_defers_new_suggestions() -> None:
    # 70 min/week → 10/day; seven 10-minute tasks fill the week, the eighth is deferred.
    tasks = [task(f"t{i}", minutes=10, day=TODAY + timedelta(days=i)) for i in range(7)]
    extra = task("extra", minutes=10, due=TODAY + timedelta(days=2))
    entries = plan([*tasks, extra], weekly=70)
    # The deadline outranks plain practice, so it takes a slot and practice is deferred.
    assert entries["extra"].placement in (Placement.KEPT, Placement.MOVED)
    deferred = [e for e in entries.values() if e.placement is Placement.DEFERRED]
    assert len(deferred) == 1 and deferred[0].scheduled_date == TODAY + timedelta(days=7)
    assert "already planned" in deferred[0].explanation


def test_conflicting_deadlines_earliest_first_and_never_dropped() -> None:
    a = task("a", minutes=20, due=TODAY + timedelta(days=1))
    b = task("b", minutes=20, due=TODAY)
    entries = plan([a, b], weekly=140)  # 20 min/day
    assert entries["b"].scheduled_date == TODAY and entries["b"].priority is PlanPriority.DEADLINE
    assert entries["a"].scheduled_date == TODAY + timedelta(days=1)
    # Two tasks due today with room for one: the second is placed anyway, flagged.
    c = task("c", minutes=20, due=TODAY)
    entries = plan([b, c], weekly=140)
    assert {e.placement for e in entries.values()} == {Placement.KEPT, Placement.OVER_BUDGET}
    assert all(e.scheduled_date == TODAY for e in entries.values())


def test_locked_in_progress_and_completed_tasks_are_never_moved() -> None:
    locked = task("locked", day=TODAY + timedelta(days=3), locked=True)
    started = task("started", status=TaskStatus.IN_PROGRESS)
    done = task("done", status=TaskStatus.COMPLETED, day=TODAY + timedelta(days=1))
    skipped = task("skipped", status=TaskStatus.SKIPPED)
    entries = plan([locked, started, done, skipped], weekly=7)  # 1 min/day: all over budget
    for tid in ("locked", "started", "done"):
        e = entries[tid]
        assert e.placement is Placement.FIXED and e.previous_date == e.scheduled_date
    assert "skipped" not in entries


def test_fixed_tasks_use_their_days_budget_first() -> None:
    locked = task("locked", minutes=20, locked=True)
    movable = task("movable", minutes=20)
    entries = plan([locked, movable], weekly=140)
    assert entries["movable"].placement is Placement.MOVED
    assert entries["movable"].scheduled_date == TODAY + timedelta(days=1)


def test_ranking_deadlines_then_evidence_gaps_then_practice() -> None:
    practice = task("practice", minutes=20, question="q1")
    gap = task("gap", minutes=20, question="q2")
    due = task("due", minutes=20, due=TODAY + timedelta(days=5))
    entries = plan(
        [practice, gap, due],
        weekly=140,
        question_skills={"q1": ["calc_bc.lhopital"], "q2": ["calc_bc.chain-rule"]},
        skill_levels={
            "calc_bc.lhopital": MasteryLevel.PROFICIENT,
            "calc_bc.chain-rule": MasteryLevel.EMERGING,
        },
    )
    order = sorted(entries.values(), key=lambda e: e.scheduled_date)
    assert [e.task_id for e in order] == ["due", "gap", "practice"]
    assert entries["due"].priority is PlanPriority.DEADLINE
    assert entries["gap"].priority is PlanPriority.EVIDENCE_GAP
    assert "Chain rule" in entries["gap"].explanation
    assert entries["practice"].priority is PlanPriority.PRACTICE


def test_no_assessment_data_plans_conservatively() -> None:
    entries = plan([task("a", question="q2")], evidence=False, question_skills={"q2": ["x.y"]})
    assert entries["a"].priority is PlanPriority.PRACTICE
    assert "No assessed work yet" in entries["a"].explanation


def test_stable_when_nothing_changed_and_overdue_tasks_move_forward() -> None:
    later = task("later", day=TODAY + timedelta(days=4))
    overdue = task("overdue", day=TODAY - timedelta(days=3))
    entries = plan([later, overdue], weekly=140)
    assert entries["later"].placement is Placement.KEPT
    assert entries["overdue"].placement is Placement.MOVED
    assert entries["overdue"].scheduled_date == TODAY
    assert entries["later"].source_event_ids == ("evt_later",)


def test_place_new_task_uses_free_days_or_defers() -> None:
    week = [task(f"t{i}", minutes=10, day=TODAY + timedelta(days=i)) for i in range(7)]
    assert place_new_task(TODAY, 140, week, 10).scheduled_date == TODAY
    full = place_new_task(TODAY, 70, week, 10)
    assert full.scheduled_date == TODAY + timedelta(days=7) and "full" in full.explanation
