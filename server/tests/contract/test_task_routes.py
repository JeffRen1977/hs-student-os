"""Step 12: persistent, course-scoped Task lifecycle."""

from __future__ import annotations

from datetime import UTC, date, datetime

from httpx import Response

from app.domain.types.task import TaskStatus
from app.schemas.task import TaskList
from tests.support import Harness, make_task


async def _list(h: Harness, sid: str, query: str = "") -> TaskList:
    response = await h.client.get(f"/api/tasks{query}", headers=h.auth(sid))
    assert response.status_code == 200, response.text
    return TaskList.model_validate(response.json())


async def test_list_filters_by_date_status_and_course(harness: Harness) -> None:
    harness.put_task(make_task("stu_alex", "task_a", scheduled=date(2026, 11, 5)))
    harness.put_task(
        make_task("stu_alex", "task_b", scheduled=date(2026, 11, 5), status=TaskStatus.SKIPPED)
    )
    all_tasks = await _list(harness, "stu_alex")
    assert [t.task_id for t in all_tasks.tasks] == [
        "task_alex_calc_01",
        "task_alex_calc_02",
        "task_alex_dsat_01",
        "task_a",
        "task_alex_dsat_02",
        "task_b",
    ]  # ordered by scheduledDate, then taskId (both enrolled courses)
    on_day = await _list(harness, "stu_alex", "?date=2026-11-05")
    assert {t.task_id for t in on_day.tasks} == {"task_a", "task_alex_dsat_02", "task_b"}
    planned = await _list(harness, "stu_alex", "?date=2026-11-05&status=PLANNED")
    assert [t.task_id for t in planned.tasks] == ["task_a", "task_alex_dsat_02"]
    by_course = await _list(harness, "stu_alex", "?courseId=calc_bc&limit=1")
    assert len(by_course.tasks) == 1 and by_course.next_cursor
    page2 = await _list(
        harness, "stu_alex", f"?courseId=calc_bc&limit=1&cursor={by_course.next_cursor}"
    )
    assert page2.tasks[0].task_id == "task_alex_calc_02"
    bad = await harness.client.get("/api/tasks?date=11/05/2026", headers=harness.auth("stu_alex"))
    assert bad.status_code == 400
    bad_cursor = await harness.client.get("/api/tasks?cursor=@@@", headers=harness.auth("stu_alex"))
    assert bad_cursor.status_code == 400


async def test_today_uses_student_timezone(harness: Harness) -> None:
    # 03:30 UTC on Nov 3 is still Nov 2 in Los Angeles (Alex) but Nov 2 23:30 in New York.
    harness.clock.set(datetime(2026, 11, 3, 3, 30, tzinfo=UTC))
    harness.put_task(make_task("stu_alex", "task_nov3", scheduled=date(2026, 11, 3)))
    alex_today = await _list(harness, "stu_alex", "?date=today")
    assert {t.task_id for t in alex_today.tasks} == {"task_alex_calc_01"}
    harness.clock.set(datetime(2026, 11, 3, 8, 30, tzinfo=UTC))  # Nov 3 in both zones
    alex_today = await _list(harness, "stu_alex", "?date=today")
    assert {t.task_id for t in alex_today.tasks} == {"task_alex_calc_02", "task_nov3"}


async def test_unenrolled_course_tasks_are_not_returned(harness: Harness) -> None:
    harness.put_task(make_task("stu_alex", "task_apush", course_id="apush"))
    tasks = await _list(harness, "stu_alex")
    assert "task_apush" not in {t.task_id for t in tasks.tasks}
    only_apush = await _list(harness, "stu_alex", "?courseId=apush")
    assert only_apush.tasks == []


async def test_get_does_not_replan_or_write(harness: Harness) -> None:
    await harness.client.get("/api/twin", headers=harness.auth("stu_alex"))  # first login
    before = harness.store.snapshot()
    await _list(harness, "stu_alex")
    await _list(harness, "stu_alex", "?date=today")
    await harness.client.get("/api/tasks/task_alex_calc_01", headers=harness.auth("stu_alex"))
    assert harness.store.snapshot() == before


async def _patch(h: Harness, task_id: str, body: dict[str, object], etag: str = '"1"') -> Response:
    return await h.client.patch(
        f"/api/tasks/{task_id}", json=body, headers={**h.auth("stu_alex"), "If-Match": etag}
    )


async def test_reschedule_lock_and_skip(harness: Harness) -> None:
    get = await harness.client.get("/api/tasks/task_alex_calc_01", headers=harness.auth("stu_alex"))
    assert get.headers["ETag"] == '"1"'
    r1 = await _patch(
        harness, "task_alex_calc_01", {"scheduledDate": "2026-11-09", "studentLocked": True}
    )
    assert r1.status_code == 200 and r1.headers["ETag"] == '"2"'
    assert r1.json()["scheduledDate"] == "2026-11-09" and r1.json()["studentLocked"] is True
    r2 = await _patch(harness, "task_alex_calc_01", {"status": "SKIPPED"}, '"2"')
    assert r2.status_code == 200 and r2.json()["status"] == "SKIPPED"
    r3 = await _patch(harness, "task_alex_calc_01", {"scheduledDate": "2026-11-10"}, '"3"')
    assert r3.status_code == 409
    assert r3.json()["error"]["code"] == "TASK_NOT_OPEN"


async def test_skip_only_from_planned(harness: Harness) -> None:
    start = await harness.client.post(
        "/api/sessions", json={"taskId": "task_alex_calc_01"}, headers=harness.cmd("stu_alex")
    )
    assert start.status_code == 201
    task = await harness.client.get(
        "/api/tasks/task_alex_calc_01", headers=harness.auth("stu_alex")
    )
    assert task.json()["status"] == "IN_PROGRESS"
    response = await _patch(
        harness, "task_alex_calc_01", {"status": "SKIPPED"}, task.headers["ETag"]
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


async def test_patch_to_completed_or_other_fields_is_rejected(harness: Harness) -> None:
    for body in (
        {"status": "COMPLETED"},
        {"status": "IN_PROGRESS"},
        {"title": "renamed"},
        {"courseId": "apush"},
        {"version": 5},
        {},
    ):
        response = await _patch(harness, "task_alex_calc_01", body)
        assert response.status_code == 400, body


async def test_patch_version_conflict_and_preconditions(harness: Harness) -> None:
    assert (await _patch(harness, "task_alex_calc_01", {"studentLocked": True})).status_code == 200
    stale = await _patch(harness, "task_alex_calc_01", {"studentLocked": False})
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
    missing = await harness.client.patch(
        "/api/tasks/task_alex_calc_01",
        json={"studentLocked": True},
        headers=harness.auth("stu_alex"),
    )
    assert missing.status_code == 428


async def test_cross_student_task_is_404(harness: Harness) -> None:
    response = await harness.client.patch(
        "/api/tasks/task_beth_calc_01",
        json={"status": "SKIPPED"},
        headers={**harness.auth("stu_alex"), "If-Match": '"1"'},
    )
    assert response.status_code == 404
    beth = await harness.client.get(
        "/api/tasks/task_beth_calc_01", headers=harness.auth("stu_beth")
    )
    assert beth.json()["status"] == "PLANNED"


async def test_patch_task_in_unenrolled_course_is_409(harness: Harness) -> None:
    await harness.client.post(
        "/api/courses/unenroll", json={"courseId": "calc_bc"}, headers=harness.cmd("stu_alex")
    )
    response = await _patch(harness, "task_alex_calc_01", {"status": "SKIPPED"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "COURSE_NOT_ENROLLED"
