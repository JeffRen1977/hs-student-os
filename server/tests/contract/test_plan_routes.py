"""Step 25: replanning as a PLANNING run, student controls, concurrency and recovery."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
from datetime import date, timedelta
from typing import Any

from app.adapters.firestore.memory_store import SimulatedCommitFailure
from app.domain.types.task import TaskReason, TaskReasonCode
from tests.support import Harness, idem, make_task

ALEX, BETH = "stu_alex", "stu_beth"
TODAY = date(2026, 11, 2)  # local date in Los Angeles at the harness START


async def replan(h: Harness, sid: str = ALEX, key: str | None = None) -> Any:
    return await h.client.post("/api/plans/replan", json={}, headers=h.cmd(sid, key))


async def get(h: Harness, path: str, sid: str = ALEX, status: int = 200) -> Any:
    r = await h.client.get(path, headers=h.auth(sid))
    assert r.status_code == status, r.text
    return r.json()


def task_doc(h: Harness, tid: str, sid: str = ALEX) -> dict[str, Any]:
    return dict(h.store.raw(f"students/{sid}/tasks/{tid}"))


def set_weekly(h: Harness, minutes: int, sid: str = ALEX) -> None:
    student = h.store.raw(f"students/{sid}")
    student["preferences"]["weeklyAvailableMinutes"] = minutes
    h.put_doc(f"students/{sid}", student)


async def test_replan_runs_as_a_planning_run_and_explains_each_task(harness: Harness) -> None:
    h = harness
    # An overdue task with a real source event, so the explanation can cite it.
    for path in ("/api/courses/unenroll", "/api/courses/enroll"):
        await h.client.post(path, json={"courseId": "calc_bc"}, headers=h.cmd(ALEX))
    feed = (await get(h, "/api/events?after=0"))["events"]
    [enrolled] = [e for e in feed if e["type"] == "course.enrolled"]
    h.put_task(
        dataclasses.replace(
            make_task(ALEX, "task_overdue", scheduled=TODAY - timedelta(days=2)),
            reason=TaskReason(
                code=TaskReasonCode.STUDENT_SCHEDULED, source_event_ids=(enrolled["eventId"],)
            ),
        )
    )
    r = await replan(h)
    assert r.status_code == 202 and r.json()["status"] == "QUEUED"
    run_id = r.json()["runId"]
    run = await get(h, f"/api/runs/{run_id}")
    assert run["kind"] == "PLANNING" and run["sessionId"] is None
    await get(h, "/api/plans/latest", status=404)  # nothing until the run executes

    assert await h.drain() == 1
    run = await get(h, f"/api/runs/{run_id}")
    assert run["status"] == "SUCCEEDED" and run["result"]["planId"]
    plan = await get(h, "/api/plans/latest")
    assert plan["planId"] == run["result"]["planId"] and plan["ruleVersion"] == "planner-rules-v1"
    assert plan["localDate"] == TODAY.isoformat() and plan["evidenceAvailable"] is False
    by_task = {e["taskId"]: e for e in plan["entries"]}
    overdue = by_task["task_overdue"]
    assert overdue["placement"] == "moved" and overdue["scheduledDate"] >= TODAY.isoformat()
    assert overdue["explanation"] and overdue["sourceEventIds"] == [enrolled["eventId"]]
    # Every cited event is a real event of this student.
    known = {e["eventId"] for e in (await get(h, "/api/events?after=0&limit=100"))["events"]}
    assert all(set(e["sourceEventIds"]) <= known for e in plan["entries"])
    assert task_doc(h, "task_overdue")["scheduledDate"] == overdue["scheduledDate"]
    assert task_doc(h, "task_overdue")["version"] == 2

    updated = [
        e
        for e in (await get(h, "/api/events?after=0&limit=100"))["events"]
        if e["type"] == "plan.updated"
    ]
    assert updated[-1]["payload"]["planId"] == plan["planId"]
    assert "task_overdue" in updated[-1]["payload"]["changedTaskIds"]
    assert await get(h, f"/api/plans/{plan['planId']}") == plan


async def test_replan_idempotency_and_one_planning_run_at_a_time(harness: Harness) -> None:
    h = harness
    key = idem()
    first, again = await replan(h, key=key), await replan(h, key=key)
    assert first.status_code == again.status_code == 202
    assert again.headers["Idempotency-Replayed"] == "true"
    assert first.json()["runId"] == again.json()["runId"]
    busy = await replan(h)
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "RUN_IN_PROGRESS"
    await h.drain()
    assert (await replan(h)).status_code == 202  # the slot is free again


async def test_concurrent_replans_and_patches_stay_consistent(harness: Harness) -> None:
    h = harness
    for i in range(4):
        h.put_task(make_task(ALEX, f"t{i}", scheduled=TODAY + timedelta(days=10)))
    results = await asyncio.gather(*(replan(h) for _ in range(3)))
    assert sorted(r.status_code for r in results) == [202, 409, 409]
    # The student locks a task after the replan is queued but before it runs.
    r = await h.client.patch(
        "/api/tasks/t0", json={"studentLocked": True}, headers={**h.auth(ALEX), "If-Match": '"1"'}
    )
    assert r.status_code == 200
    before = sorted(h.store.paths(f"students/{ALEX}/tasks/"))
    await h.drain()
    assert sorted(h.store.paths(f"students/{ALEX}/tasks/")) == before  # none added or lost
    assert task_doc(h, "t0")["scheduledDate"] == (TODAY + timedelta(days=10)).isoformat()
    assert all(
        task_doc(h, f"t{i}")["scheduledDate"] < (TODAY + timedelta(days=7)).isoformat()
        for i in (1, 2, 3)
    )
    plan = await get(h, "/api/plans/latest")
    # A locked task outside the horizon is neither moved nor listed.
    assert "t0" not in {e["taskId"] for e in plan["entries"]}


async def test_stale_patch_after_replan_is_a_version_conflict(harness: Harness) -> None:
    h = harness
    h.put_task(make_task(ALEX, "t_far", scheduled=TODAY + timedelta(days=20)))
    await replan(h)
    await h.drain()
    r = await h.client.patch(
        "/api/tasks/t_far",
        json={"studentLocked": True},
        headers={**h.auth(ALEX), "If-Match": '"1"'},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "VERSION_CONFLICT"


async def test_full_week_defers_and_explains(harness: Harness) -> None:
    h = harness
    set_weekly(h, 70)  # 10 minutes a day
    for i in range(9):
        h.put_task(dataclasses.replace(make_task(ALEX, f"w{i}", scheduled=TODAY), duration_min=10))
    await replan(h)
    await h.drain()
    plan = await get(h, "/api/plans/latest")
    placements = [e["placement"] for e in plan["entries"] if e["taskId"].startswith("w")]
    assert placements.count("deferred") >= 2
    deferred = [e for e in plan["entries"] if e["placement"] == "deferred"]
    assert all(e["scheduledDate"] == (TODAY + timedelta(days=7)).isoformat() for e in deferred)
    assert all("already planned" in e["explanation"] for e in deferred)


async def test_crash_during_planning_commit_leaves_no_partial_plan(harness: Harness) -> None:
    h = harness
    h.put_task(make_task(ALEX, "t_far", scheduled=TODAY + timedelta(days=20)))
    run_id = (await replan(h)).json()["runId"]
    await h.services.dispatcher.dispatch_pending()
    original = h.store.commits
    real = h.store.run_transaction
    calls = {"n": 0}

    async def failing(fn):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 2:  # acquire commits; the planning commit fails
            h.store.fail_next_commits = 1
        return await real(fn)

    h.store.run_transaction = failing  # type: ignore[method-assign]
    with contextlib.suppress(SimulatedCommitFailure):
        await h.queue.drain(h.services.deliveries.process)
    h.store.run_transaction = real  # type: ignore[method-assign]
    assert h.store.commits == original + 1  # only the lease
    assert task_doc(h, "t_far")["version"] == 1 and not h.store.paths(f"students/{ALEX}/plans/")
    assert (await get(h, f"/api/runs/{run_id}"))["status"] == "RUNNING"

    # The lease expires; recovery re-queues; the second attempt plans exactly once.
    h.clock.advance(seconds=h.services.settings.run_lease_seconds + 1)
    assert await h.services.recovery.requeue_stalled() == 1
    await h.settle()
    assert (await get(h, f"/api/runs/{run_id}"))["status"] == "SUCCEEDED"
    assert len(h.store.paths(f"students/{ALEX}/plans/")) == 1
    assert task_doc(h, "t_far")["version"] == 2


async def test_student_controls_skip_reason_and_reschedule_lock(harness: Harness) -> None:
    h = harness
    r = await h.client.patch(
        "/api/tasks/task_alex_calc_02",
        json={"scheduledDate": "2026-11-05"},
        headers={**h.auth(ALEX), "If-Match": '"1"'},
    )
    assert r.status_code == 200 and r.json()["studentLocked"] is True
    r = await h.client.patch(
        "/api/tasks/task_alex_calc_02",
        json={"scheduledDate": "2026-11-06", "studentLocked": False},
        headers={**h.auth(ALEX), "If-Match": '"2"'},
    )
    assert r.json()["studentLocked"] is False  # an explicit choice in the same patch wins
    r = await h.client.patch(
        "/api/tasks/task_alex_calc_01",
        json={"status": "SKIPPED", "skipReason": "already_know"},
        headers={**h.auth(ALEX), "If-Match": '"1"'},
    )
    assert r.status_code == 200 and r.json()["skipReason"] == "already_know"
    r = await h.client.patch(
        "/api/tasks/task_alex_calc_02",
        json={"skipReason": "no_time"},
        headers={**h.auth(ALEX), "If-Match": '"3"'},
    )
    assert r.status_code == 400  # a reason without skipping is rejected


async def test_plans_are_isolated_and_require_auth(harness: Harness) -> None:
    h = harness
    await replan(h)
    await h.drain()
    plan = await get(h, "/api/plans/latest")
    await get(h, f"/api/plans/{plan['planId']}", sid=BETH, status=404)
    await get(h, "/api/plans/latest", sid=BETH, status=404)
    assert (await h.client.post("/api/plans/replan", json={})).status_code == 401
    r = await h.client.post("/api/plans/replan", json={}, headers=h.auth(ALEX))
    assert r.status_code == 400 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    r = await h.client.post("/api/plans/replan", json={"studentId": BETH}, headers=h.cmd(ALEX))
    assert r.status_code == 400  # no body fields, and never a client-chosen student
