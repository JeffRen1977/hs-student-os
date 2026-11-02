"""Step 28: timezone-aware scheduled planning.

The harness clock starts Monday 2026-11-02 18:00 UTC. Seeded schedules: Beth (New York)
is due 2026-11-03 04:00 EST = 09:00 UTC; Alex (Los Angeles) 04:00 PST = 12:00 UTC.
US DST ended 2026-11-01 and starts again 2027-03-14.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.domain.local_time import at_local, next_at_local
from app.domain.planning_schedule import PlanningSchedulePolicy, ScheduleOutcome
from app.workers.run_worker import create_worker_app
from app.workers.scheduler.planning_scheduler import PlanningScheduler
from tests.support import Harness, build_harness

ALEX, BETH = "stu_alex", "stu_beth"
NY = "America/New_York"


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)  # type: ignore[misc]


def state(h: Harness, sid: str) -> dict[str, Any]:
    doc = h.store.raw(f"students/{sid}/planState/current")
    assert doc is not None
    return dict(doc)


def plans(h: Harness, sid: str) -> list[dict[str, Any]]:
    return [h.store.raw(p) for p in h.store.paths(f"students/{sid}/plans/")]


def planning_runs(h: Harness, sid: str) -> list[dict[str, Any]]:
    runs = [h.store.raw(p) for p in h.store.paths(f"students/{sid}/runs/")]
    return [r for r in runs if r["kind"] == "PLANNING"]


def scheduler(h: Harness, wall: time) -> PlanningScheduler:
    s = h.services
    return PlanningScheduler(s.uow, s.operations, s.clock, s.ids, PlanningSchedulePolicy(wall))


async def test_seeded_schedules_use_each_students_local_morning(harness: Harness) -> None:
    h = harness
    assert state(h, BETH)["nextDueAt"] == utc(2026, 11, 3, 9)
    assert state(h, ALEX)["nextDueAt"] == utc(2026, 11, 3, 12)


async def test_one_scheduled_plan_per_local_day_in_each_timezone(harness: Harness) -> None:
    h = harness
    run_due = h.services.planning_scheduler.run_due
    assert await run_due() == {}  # nobody is due yet

    h.clock.set(utc(2026, 11, 3, 9, 1))  # 04:01 in New York, 01:01 in Los Angeles
    assert await run_due() == {ScheduleOutcome.QUEUED: 1}
    await h.settle()
    [plan] = plans(h, BETH)
    assert plan["trigger"] == "scheduled" and plan["localDate"] == "2026-11-03"
    assert planning_runs(h, ALEX) == []
    latest = await h.client.get("/api/plans/latest", headers=h.auth(BETH))
    assert latest.json()["trigger"] == "scheduled"
    events = (await h.client.get("/api/events", headers=h.auth(BETH))).json()["events"]
    [updated] = [e for e in events if e["type"] == "plan.updated"]
    assert updated["payload"]["reason"] == "scheduled"
    st = state(h, BETH)
    assert st["lastScheduledLocalDate"] == "2026-11-03"
    assert st["nextDueAt"] == utc(2026, 11, 4, 9) and st["activeRunId"] is None

    # Duplicate scheduler invocations, sequential and concurrent: nothing more.
    assert await run_due() == {}
    await asyncio.gather(run_due(), run_due())
    h.clock.set(utc(2026, 11, 3, 12, 0))  # Alex's 04:00
    results = await asyncio.gather(run_due(), run_due(), run_due())
    assert sum(r[ScheduleOutcome.QUEUED] for r in results) == 1
    await h.settle()
    assert len(plans(h, ALEX)) == 1 and len(plans(h, BETH)) == 1


async def test_duplicate_due_rows_in_one_scan_queue_one_run(harness: Harness) -> None:
    """Even if the scan lists a student twice, the per-student transaction re-checks."""
    h = harness
    h.clock.set(utc(2026, 11, 3, 9, 5))
    s = h.services
    policy = PlanningSchedulePolicy()

    class DoubledOps:
        async def due_plan_schedules(self, *, due_before: datetime, limit: int) -> list[str]:
            return [BETH, BETH, BETH]

    dup = PlanningScheduler(s.uow, DoubledOps(), s.clock, s.ids, policy)  # type: ignore[arg-type]
    outcomes = await dup.run_due()
    assert outcomes == {ScheduleOutcome.QUEUED: 1, ScheduleOutcome.NOT_DUE: 2}
    assert len(planning_runs(h, BETH)) == 1


async def test_downtime_catches_up_with_one_plan_for_today(harness: Harness) -> None:
    h = harness
    h.clock.set(utc(2026, 11, 6, 15))  # the scheduler was down for three local mornings
    outcomes = await h.services.planning_scheduler.run_due()
    assert outcomes == {ScheduleOutcome.QUEUED: 2}  # Alex and Beth, once each
    await h.settle()
    for sid in (ALEX, BETH):
        [plan] = plans(h, sid)
        assert plan["localDate"] == "2026-11-06"
    assert state(h, BETH)["nextDueAt"] == utc(2026, 11, 7, 9)
    assert state(h, ALEX)["nextDueAt"] == utc(2026, 11, 7, 12)


async def test_a_worker_crash_after_queueing_is_recovered_without_a_second_plan(
    harness: Harness,
) -> None:
    h = harness
    h.clock.set(utc(2026, 11, 3, 9, 1))
    await h.services.planning_scheduler.run_due()
    # The queue lost the delivery; the stalled-run scan re-queues the same run.
    h.clock.advance(minutes=10)
    assert await h.services.recovery.requeue_stalled() == 1
    await h.settle()
    assert len(plans(h, BETH)) == 1 and len(planning_runs(h, BETH)) == 1


def test_dst_wall_times_resolve_once() -> None:
    # Spring forward: 02:30 does not exist on 2027-03-14 in New York → 03:30 EDT.
    assert at_local(date(2027, 3, 14), time(2, 30), NY) == utc(2027, 3, 14, 7, 30)
    # Fall back: 01:30 happens twice on 2026-11-01 → the first (EDT) occurrence.
    assert at_local(date(2026, 11, 1), time(1, 30), NY) == utc(2026, 11, 1, 5, 30)
    # 04:00 is 23 h after the previous 04:00 in spring and 25 h in autumn.
    spring = at_local(date(2027, 3, 14), time(4), NY) - at_local(date(2027, 3, 13), time(4), NY)
    autumn = at_local(date(2026, 11, 1), time(4), NY) - at_local(date(2026, 10, 31), time(4), NY)
    assert (spring.total_seconds(), autumn.total_seconds()) == (23 * 3600, 25 * 3600)
    assert next_at_local(utc(2026, 11, 1, 5, 30), time(1, 30), NY) == utc(2026, 11, 2, 6, 30)


@pytest.mark.parametrize(
    ("wall", "first_due", "repeat_at", "next_due"),
    [
        # Fall back: the 01:30 slot repeats an hour later. The repeat must not plan again.
        (time(1, 30), utc(2026, 11, 1, 5, 30), utc(2026, 11, 1, 6, 30), utc(2026, 11, 2, 6, 30)),
        # Spring forward: the 02:30 slot does not exist; it runs at 03:30 EDT, once.
        (time(2, 30), utc(2027, 3, 14, 7, 30), utc(2027, 3, 14, 8, 30), utc(2027, 3, 15, 6, 30)),
    ],
)
async def test_dst_days_plan_exactly_once(
    harness: Harness, wall: time, first_due: datetime, repeat_at: datetime, next_due: datetime
) -> None:
    h = harness
    h.put_doc(f"students/{ALEX}/planState/current", {"studentId": ALEX, "version": 1})
    h.put_doc(
        f"students/{BETH}/planState/current",
        {"studentId": BETH, "nextDueAt": first_due, "timezone": NY, "version": 1},
    )
    sched = scheduler(h, wall)
    h.clock.set(first_due)
    assert await sched.run_due() == {ScheduleOutcome.QUEUED: 1}
    await h.settle()
    assert state(h, BETH)["nextDueAt"] == next_due
    h.clock.set(repeat_at)
    assert await sched.run_due() == {}
    # Even if a stale schedule said "due" again during the repeated hour, the local date
    # is already covered.
    h.put_doc(
        f"students/{BETH}/planState/current",
        {**state(h, BETH), "nextDueAt": repeat_at},
    )
    assert await sched.run_due() == {ScheduleOutcome.ALREADY_PLANNED: 1}
    assert len(plans(h, BETH)) == 1


async def test_timezone_change_moves_the_schedule_without_planning_a_day_twice(
    harness: Harness,
) -> None:
    h = harness
    h.clock.set(utc(2026, 11, 3, 9, 1))
    await h.services.planning_scheduler.run_due()
    await h.settle()
    assert len(plans(h, BETH)) == 1  # Tuesday planned in New York

    # 10:00 UTC: Beth flies to Los Angeles (02:00 Tuesday there).
    h.clock.set(utc(2026, 11, 3, 10))
    twin = await h.client.get("/api/twin", headers=h.auth(BETH))
    r = await h.client.patch(
        "/api/twin",
        json={"preferences": {"timezone": "America/Los_Angeles"}},
        headers={**h.auth(BETH), "If-Match": twin.headers["ETag"]},
    )
    assert r.status_code == 200, r.text
    st = state(h, BETH)
    assert st["timezone"] == "America/Los_Angeles"
    assert st["nextDueAt"] == utc(2026, 11, 3, 12)  # 04:00 Tuesday in Los Angeles

    h.clock.set(utc(2026, 11, 3, 12, 1))  # also Alex's 04:00: he is queued as usual
    assert await h.services.planning_scheduler.run_due() == {
        ScheduleOutcome.ALREADY_PLANNED: 1, ScheduleOutcome.QUEUED: 1
    }  # fmt: skip
    await h.settle()
    assert len(plans(h, BETH)) == 1  # Tuesday is not planned twice
    assert state(h, BETH)["nextDueAt"] == utc(2026, 11, 4, 12)  # Wednesday 04:00 PST

    h.clock.set(utc(2026, 11, 4, 12, 1))
    await h.services.planning_scheduler.run_due()
    await h.settle()
    assert sorted(p["localDate"] for p in plans(h, BETH)) == ["2026-11-03", "2026-11-04"]


async def test_scheduled_pass_coalesces_into_a_pending_student_replan(harness: Harness) -> None:
    h = harness
    h.clock.set(utc(2026, 11, 3, 8, 59))
    r = await h.client.post("/api/plans/replan", json={}, headers=h.cmd(BETH))
    assert r.status_code == 202
    h.clock.set(utc(2026, 11, 3, 9, 1))  # scheduled time comes before the replan ran
    assert await h.services.planning_scheduler.run_due() == {ScheduleOutcome.COALESCED: 1}
    await h.settle()
    [plan] = plans(h, BETH)
    assert plan["trigger"] == "student" and plan["localDate"] == "2026-11-03"
    assert len(planning_runs(h, BETH)) == 1
    st = state(h, BETH)
    assert st["activeRunId"] is None and st["lastScheduledLocalDate"] == "2026-11-03"


async def test_student_replan_while_scheduled_run_is_pending_is_rejected(harness: Harness) -> None:
    h = harness
    h.clock.set(utc(2026, 11, 3, 9, 1))
    await h.services.planning_scheduler.run_due()
    busy = await h.client.post("/api/plans/replan", json={}, headers=h.cmd(BETH))
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "RUN_IN_PROGRESS"
    await h.settle()
    again = await h.client.post("/api/plans/replan", json={}, headers=h.cmd(BETH))
    assert again.status_code == 202
    await h.settle()
    assert [p["trigger"] for p in sorted(plans(h, BETH), key=lambda p: p["createdAt"])] == [
        "scheduled",
        "student",
    ]


async def test_reading_tasks_never_plans_even_when_a_pass_is_due(harness: Harness) -> None:
    h = harness
    h.clock.set(utc(2026, 11, 3, 9, 30))
    await h.client.get("/api/twin", headers=h.auth(BETH))  # first sign-in maps the uid
    before = h.store.snapshot()
    for path in ("/api/tasks", "/api/tasks?date=today", "/api/plans/latest"):
        await h.client.get(path, headers=h.auth(BETH))
    assert h.store.snapshot() == before


async def test_first_enrollment_starts_the_schedule(harness: Harness) -> None:
    h = harness
    h.store.put(f"students/{BETH}/planState/current", {"studentId": BETH, "version": 1})
    h.put_doc(
        f"students/{BETH}/enrollments/calc_bc",
        {"courseId": "calc_bc", "status": "unenrolled", "enrolledAt": h.clock.now(),
         "unenrolledAt": h.clock.now()},
    )  # fmt: skip
    r = await h.client.post(
        "/api/courses/enroll", json={"courseId": "calc_bc"}, headers=h.cmd(BETH)
    )
    assert r.status_code == 200, r.text
    assert state(h, BETH)["nextDueAt"] == utc(2026, 11, 3, 9)


async def test_schedule_route_needs_a_service_identity(clean_env: pytest.MonkeyPatch) -> None:
    h = build_harness(clean_env, worker_service_token=SecretStr("local-worker-token-123"))
    client = AsyncClient(
        transport=ASGITransport(app=create_worker_app(h.services.settings, h.services)),
        base_url="http://worker",
    )
    for path in ("/internal/planning/schedule", "/internal/reminders/deliver"):
        assert (await client.post(path)).status_code == 401
        assert (await client.post(path, headers=h.auth(BETH))).status_code == 401
    h.clock.set(utc(2026, 11, 3, 9, 1))
    ok = await client.post(
        "/internal/planning/schedule",
        headers={"Authorization": "Bearer local-worker-token-123"},
    )
    assert ok.status_code == 200 and ok.json() == {"count": 1}
