"""Steps 10–11: catalog availability, enrollment lifecycle, per-course agent activation."""

from __future__ import annotations

from httpx import Response

from tests.support import Harness, idem, make_task


async def _catalog(h: Harness, sid: str) -> dict[str, dict[str, object]]:
    response = await h.client.get("/api/courses/catalog", headers=h.auth(sid))
    assert response.status_code == 200
    return {c["courseId"]: c for c in response.json()["courses"]}


def _revoke_calc(h: Harness, sid: str) -> None:
    h.put_doc(
        f"students/{sid}/access/current", {"apCourses": [], "dsat": False, "admissions": False}
    )


async def _enroll(h: Harness, sid: str, course: str, key: str | None = None) -> Response:
    return await h.client.post(
        "/api/courses/enroll", json={"courseId": course}, headers=h.cmd(sid, key)
    )


async def _unenroll(h: Harness, sid: str, course: str, key: str | None = None) -> Response:
    return await h.client.post(
        "/api/courses/unenroll", json={"courseId": course}, headers=h.cmd(sid, key)
    )


async def test_catalog_reflects_entitlements_per_student(harness: Harness) -> None:
    alex = await _catalog(harness, "stu_alex")
    assert set(alex) == {"calc_bc", "apush", "physics_c", "dsat"}
    assert alex["calc_bc"]["status"] == "enrolled"
    assert alex["dsat"]["entitled"] is True and alex["dsat"]["status"] == "enrolled"
    assert alex["apush"]["status"] == "coming_soon"
    assert alex["calc_bc"]["agent"]["supportedTaskTypes"] == ["SOCRATIC_STUDY", "FRQ_PRACTICE"]
    _revoke_calc(harness, "stu_beth")
    await _unenroll(harness, "stu_beth", "calc_bc")
    beth = await _catalog(harness, "stu_beth")
    assert beth["calc_bc"]["status"] == "locked"
    assert beth["dsat"]["entitled"] is False and beth["dsat"]["status"] == "locked"


async def test_course_detail_and_unknown_course(harness: Harness) -> None:
    ok = await harness.client.get("/api/courses/calc_bc", headers=harness.auth("stu_alex"))
    assert ok.status_code == 200 and ok.json()["status"] == "enrolled"
    missing = await harness.client.get("/api/courses/latin_ap", headers=harness.auth("stu_alex"))
    assert missing.status_code == 404
    bad = await harness.client.get("/api/courses/Not-Valid!", headers=harness.auth("stu_alex"))
    assert bad.status_code == 400


async def test_enroll_requires_idempotency_key(harness: Harness) -> None:
    response = await harness.client.post(
        "/api/courses/enroll", json={"courseId": "calc_bc"}, headers=harness.auth("stu_alex")
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    short = await harness.client.post(
        "/api/courses/enroll",
        json={"courseId": "calc_bc"},
        headers={**harness.auth("stu_alex"), "Idempotency-Key": "short"},
    )
    assert short.status_code == 400


async def test_enroll_planned_course_is_409(harness: Harness) -> None:
    response = await _enroll(harness, "stu_alex", "apush")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "COURSE_NOT_AVAILABLE"


async def test_enroll_without_entitlement_is_403(harness: Harness) -> None:
    _revoke_calc(harness, "stu_beth")
    await _unenroll(harness, "stu_beth", "calc_bc")
    response = await _enroll(harness, "stu_beth", "calc_bc")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "COURSE_ACCESS_REQUIRED"


async def test_unknown_course_enroll_is_404(harness: Harness) -> None:
    response = await _enroll(harness, "stu_alex", "latin_ap")
    assert response.status_code == 404


async def test_unenroll_reenroll_lifecycle_preserves_history(harness: Harness) -> None:
    harness.put_task(make_task("stu_alex", "task_hist"))
    harness.put_doc(
        "students/stu_alex/mastery/calc_bc.chain-rule",
        {"skillId": "calc_bc.chain-rule", "level": "emerging", "independentEvidenceCount": 1},
    )
    off = await _unenroll(harness, "stu_alex", "calc_bc")
    assert off.status_code == 200 and off.json()["status"] == "unenrolled"
    enrolled = await harness.client.get("/api/courses/enrolled", headers=harness.auth("stu_alex"))
    assert [e["courseId"] for e in enrolled.json()["enrollments"]] == ["dsat"]
    agent = await harness.client.get("/api/courses/calc_bc/agent", headers=harness.auth("stu_alex"))
    assert agent.status_code == 404
    tasks = await harness.client.get("/api/tasks", headers=harness.auth("stu_alex"))
    assert {t["courseId"] for t in tasks.json()["tasks"]} == {"dsat"}  # calc hidden...

    on = await _enroll(harness, "stu_alex", "calc_bc")
    assert on.status_code == 200 and on.json()["status"] == "active"
    tasks = await harness.client.get("/api/tasks", headers=harness.auth("stu_alex"))
    assert "task_hist" in {t["taskId"] for t in tasks.json()["tasks"]}  # ...and back again
    agent = await harness.client.get("/api/courses/calc_bc/agent", headers=harness.auth("stu_alex"))
    assert agent.status_code == 200
    assert agent.json()["masterySummary"]["calc_bc.chain-rule"]["independentEvidenceCount"] == 1
    assert "systemPrompt" not in agent.text and "tools" not in agent.json()

    events = sorted(
        (harness.store.raw(p) for p in harness.store.paths("students/stu_alex/events/")),
        key=lambda e: e["sequence"],
    )
    assert [(e["type"], e["sequence"]) for e in events] == [
        ("course.unenrolled", 1),
        ("course.enrolled", 2),
    ]
    twin = await harness.client.get("/api/twin", headers=harness.auth("stu_alex"))
    assert twin.json()["latestEventSequence"] == 2


async def test_duplicate_enrollment_is_idempotent(harness: Harness) -> None:
    key = idem()
    first = await _enroll(harness, "stu_alex", "calc_bc", key)
    again = await _enroll(harness, "stu_alex", "calc_bc", key)
    other_key = await _enroll(harness, "stu_alex", "calc_bc")
    assert first.status_code == again.status_code == other_key.status_code == 200
    assert first.json() == again.json() == other_key.json()
    assert again.headers["Idempotency-Replayed"] == "true"
    assert harness.store.paths("students/stu_alex/events/") == []  # already enrolled: no event


async def test_same_key_different_body_is_409(harness: Harness) -> None:
    key = idem()
    await _unenroll(harness, "stu_alex", "calc_bc", key)
    response = await _enroll(harness, "stu_alex", "calc_bc", key)  # different route scope
    assert response.status_code == 200
    conflict = await harness.client.post(
        "/api/courses/unenroll", json={"courseId": "dsat"}, headers=harness.cmd("stu_alex", key)
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_unenroll_with_open_session_is_409(harness: Harness) -> None:
    session = await harness.client.post(
        "/api/sessions", json={"taskId": "task_alex_calc_01"}, headers=harness.cmd("stu_alex")
    )
    assert session.status_code == 201
    response = await _unenroll(harness, "stu_alex", "calc_bc")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "OPEN_SESSION_EXISTS"
    sid = session.json()["sessionId"]
    abandon = await harness.client.post(
        f"/api/sessions/{sid}/abandon", json={}, headers=harness.cmd("stu_alex")
    )
    assert abandon.status_code == 200
    assert (await _unenroll(harness, "stu_alex", "calc_bc")).status_code == 200


async def test_enrolled_and_agent_show_only_own_enrollments(harness: Harness) -> None:
    await _unenroll(harness, "stu_beth", "calc_bc")
    alex = await harness.client.get("/api/courses/enrolled", headers=harness.auth("stu_alex"))
    beth = await harness.client.get("/api/courses/enrolled", headers=harness.auth("stu_beth"))
    assert [e["courseId"] for e in alex.json()["enrollments"]] == ["calc_bc", "dsat"]
    assert alex.json()["enrollments"][0]["agent"]["agentType"] == "AP_BASE"
    assert beth.json()["enrollments"] == []
    agent = await harness.client.get("/api/courses/calc_bc/agent", headers=harness.auth("stu_beth"))
    assert agent.status_code == 404
    unknown = await harness.client.get(
        "/api/courses/latin_ap/agent", headers=harness.auth("stu_alex")
    )
    assert unknown.status_code == 404
