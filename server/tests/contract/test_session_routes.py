"""Step 13: Session creation and lifecycle."""

from __future__ import annotations

import asyncio

import pytest
from httpx import Response

from app.bootstrap import build_services
from app.domain.types.task import TaskStatus
from app.main import create_app
from app.schemas.session import Session
from tests.support import Harness, harness_settings, idem, make_task


async def _start(h: Harness, sid: str, task_id: str, key: str | None = None) -> Response:
    return await h.client.post("/api/sessions", json={"taskId": task_id}, headers=h.cmd(sid, key))


async def test_create_session_for_enrolled_entitled_course(harness: Harness) -> None:
    response = await _start(harness, "stu_alex", "task_alex_calc_01")
    assert response.status_code == 201
    session = Session.model_validate(response.json())
    assert session.status == "OPEN" and session.active_run_id is None
    # Context comes from the pinned pack, not the request.
    assert session.context_version.pack == "1.0.0"
    assert session.context_version.workflow == "calc-practice-v1"
    assert session.completion.reason == "accepted_assessment_required"
    task = await harness.client.get(
        "/api/tasks/task_alex_calc_01", headers=harness.auth("stu_alex")
    )
    assert task.json()["status"] == "IN_PROGRESS" and task.json()["version"] == 2
    events = [harness.store.raw(p) for p in harness.store.paths("students/stu_alex/events/")]
    assert [(e["type"], e["payload"]) for e in events] == [
        ("session.started", {"taskId": "task_alex_calc_01"})
    ]
    stored = harness.store.raw(f"students/stu_alex/sessions/{session.session_id}")
    assert stored["agentSkills"] == ["socratic-guidance", "rubric-assessment"]


async def test_request_cannot_override_course_or_agent(harness: Harness) -> None:
    response = await harness.client.post(
        "/api/sessions",
        json={"taskId": "task_alex_calc_01", "courseId": "apush"},
        headers=harness.cmd("stu_alex"),
    )
    assert response.status_code == 400


async def test_planned_course_is_409(harness: Harness) -> None:
    harness.put_task(make_task("stu_alex", "task_apush", course_id="apush"))
    response = await _start(harness, "stu_alex", "task_apush")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "COURSE_NOT_AVAILABLE"


async def test_not_entitled_is_403(harness: Harness) -> None:
    harness.put_doc(
        "students/stu_beth/access/current", {"apCourses": [], "dsat": False, "admissions": False}
    )
    response = await _start(harness, "stu_beth", "task_beth_calc_01")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "COURSE_ACCESS_REQUIRED"


async def test_not_enrolled_is_409(harness: Harness) -> None:
    await harness.client.post(
        "/api/courses/unenroll", json={"courseId": "calc_bc"}, headers=harness.cmd("stu_alex")
    )
    response = await _start(harness, "stu_alex", "task_alex_calc_01")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "COURSE_NOT_ENROLLED"


async def test_second_start_returns_existing_open_session(harness: Harness) -> None:
    first = await _start(harness, "stu_alex", "task_alex_calc_01")
    second = await _start(harness, "stu_alex", "task_alex_calc_01")
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["sessionId"] == second.json()["sessionId"]
    listed = await harness.client.get(
        "/api/sessions?taskId=task_alex_calc_01", headers=harness.auth("stu_alex")
    )
    assert len(listed.json()["sessions"]) == 1


async def test_concurrent_starts_create_one_session(harness: Harness) -> None:
    responses = await asyncio.gather(
        *(_start(harness, "stu_alex", "task_alex_calc_01") for _ in range(5))
    )
    assert sorted(r.status_code for r in responses) == [200, 200, 200, 200, 201]
    assert len({r.json()["sessionId"] for r in responses}) == 1
    assert len(harness.store.paths("students/stu_alex/sessions/")) == 1


async def test_same_idempotency_key_returns_original(harness: Harness) -> None:
    key = idem()
    first = await _start(harness, "stu_alex", "task_alex_calc_01", key)
    replay = await _start(harness, "stu_alex", "task_alex_calc_01", key)
    assert replay.status_code == 201
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == first.json()
    conflict = await _start(harness, "stu_alex", "task_alex_calc_02", key)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    # Keys are per actor: Beth reusing Alex's key is just a new command for Beth.
    beth = await _start(harness, "stu_beth", "task_beth_calc_01", key)
    assert beth.status_code == 201


async def test_cross_student_task_is_404(harness: Harness) -> None:
    response = await _start(harness, "stu_alex", "task_beth_calc_01")
    assert response.status_code == 404
    first = await _start(harness, "stu_beth", "task_beth_calc_01")
    sid = first.json()["sessionId"]
    for path in (
        f"/api/sessions/{sid}",
        f"/api/sessions/{sid}/messages",
        f"/api/sessions/{sid}/submissions",
    ):
        assert (await harness.client.get(path, headers=harness.auth("stu_alex"))).status_code == 404
    abandon = await harness.client.post(
        f"/api/sessions/{sid}/abandon", json={}, headers=harness.cmd("stu_alex")
    )
    assert abandon.status_code == 404


@pytest.mark.parametrize("status", [TaskStatus.COMPLETED, TaskStatus.SKIPPED])
async def test_closed_task_is_409(harness: Harness, status: TaskStatus) -> None:
    harness.put_task(make_task("stu_alex", "task_closed", status=status))
    response = await _start(harness, "stu_alex", "task_closed")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_NOT_OPEN"


async def test_abandon_returns_task_to_planned_and_allows_new_attempt(harness: Harness) -> None:
    first = await _start(harness, "stu_alex", "task_alex_calc_01")
    sid = first.json()["sessionId"]
    abandon = await harness.client.post(
        f"/api/sessions/{sid}/abandon", json={}, headers=harness.cmd("stu_alex")
    )
    assert abandon.status_code == 200
    assert abandon.json()["status"] == "ABANDONED"
    assert abandon.json()["completion"] == {"eligible": False, "reason": "session_closed"}
    task = await harness.client.get(
        "/api/tasks/task_alex_calc_01", headers=harness.auth("stu_alex")
    )
    assert task.json()["status"] == "PLANNED"
    second = await _start(harness, "stu_alex", "task_alex_calc_01")
    assert second.status_code == 201 and second.json()["sessionId"] != sid
    listed = await harness.client.get(
        "/api/sessions?taskId=task_alex_calc_01", headers=harness.auth("stu_alex")
    )
    assert [s["status"] for s in listed.json()["sessions"]] == ["ABANDONED", "OPEN"]


async def test_abandon_rejects_body_fields(harness: Harness) -> None:
    first = await _start(harness, "stu_alex", "task_alex_calc_01")
    response = await harness.client.post(
        f"/api/sessions/{first.json()['sessionId']}/abandon",
        json={"status": "COMPLETED"},
        headers=harness.cmd("stu_alex"),
    )
    assert response.status_code == 400


async def test_session_persists_across_restart(
    harness: Harness, clean_env: pytest.MonkeyPatch
) -> None:
    first = await _start(harness, "stu_alex", "task_alex_calc_01")
    settings = harness_settings(clean_env)
    services = build_services(settings, store=harness.store, clock=harness.clock)
    from httpx import ASGITransport, AsyncClient

    client = AsyncClient(
        transport=ASGITransport(app=create_app(settings, services)), base_url="http://t"
    )
    sid = first.json()["sessionId"]
    response = await client.get(f"/api/sessions/{sid}", headers=harness.auth("stu_alex"))
    assert response.status_code == 200 and response.json() == first.json()
    resumed = await client.post(
        "/api/sessions", json={"taskId": "task_alex_calc_01"}, headers=harness.cmd("stu_alex")
    )
    assert resumed.status_code == 200 and resumed.json()["sessionId"] == sid
