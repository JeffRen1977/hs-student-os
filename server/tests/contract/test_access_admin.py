"""Step 42: platform admins grant and revoke course access (API.md §6.5.6).

Replaces hand edits of `students/{id}/access/current`. Each change writes the access
record, an audit entry, a filtered `access.changed` student event and the idempotency
record in one transaction. Revoking keeps every record and blocks only new work.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.adapters.firestore.memory_store import SimulatedCommitFailure
from app.domain.commands import CommandKey
from app.domain.errors import DomainError, ErrorCode
from app.domain.types.access import AccessChange
from app.domain.types.actor import ActorContext, ActorRole, PlatformActor
from tests.support import Harness, build_harness, idem

ADMIN, REVIEWER, AUTHOR = "admin_platform", "reviewer_platform", "author_hsos"
ALEX, BETH, PARENT = "stu_alex", "stu_beth", "parent_alex"
BETH_ACCESS = f"/api/admin/students/{BETH}/access"
REASON = "Pilot cohort: Digital SAT."


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch) -> Harness:
    return build_harness(clean_env)


async def get(h: Harness, path: str, uid: str = ADMIN, status: int = 200) -> Any:
    r = await h.client.get(path, headers=h.auth(uid))
    assert r.status_code == status, r.text
    return r.json()


async def post(
    h: Harness, path: str, body: dict[str, Any], uid: str = ADMIN, status: int = 200,
    key: str | None = None,
) -> Any:  # fmt: skip
    r = await h.client.post(path, json=body, headers=h.cmd(uid, key))
    assert r.status_code == status, r.text
    return r.json()


async def grant(h: Harness, sid: str = BETH, course: str = "dsat", **kw: Any) -> Any:
    path = f"/api/admin/students/{sid}/access/grant"
    return await post(h, path, {"courseId": course, "reason": REASON}, **kw)


async def revoke(h: Harness, sid: str = BETH, course: str = "dsat", **kw: Any) -> Any:
    path = f"/api/admin/students/{sid}/access/revoke"
    return await post(h, path, {"courseId": course, "reason": "Left the pilot."}, **kw)


def doc(h: Harness, path: str) -> dict[str, Any] | None:
    return h.store.snapshot().get(path)


def audit_docs(h: Harness, sid: str) -> list[dict[str, Any]]:
    prefix = f"students/{sid}/accessAudit/"
    return [d for p, d in h.store.snapshot().items() if p.startswith(prefix)]


async def events(h: Harness, sid: str, type_: str) -> list[dict[str, Any]]:
    page = await get(h, "/api/events?after=0&limit=100", sid)
    return [e for e in page["events"] if e["type"] == type_]


def dsat(view: dict[str, Any]) -> dict[str, Any]:
    return next(c for c in view["courses"] if c["courseId"] == "dsat")


async def test_only_platform_admins_reach_the_admin_routes(h: Harness) -> None:
    for uid in (AUTHOR, REVIEWER, ALEX, BETH, PARENT):
        await get(h, BETH_ACCESS, uid, status=403)
        await grant(h, uid=uid, status=403)
        await revoke(h, uid=uid, status=403)
        body = {"studentIds": [BETH], "courseId": "dsat", "change": "grant", "reason": "x"}
        await post(h, "/api/admin/access/bulk", body, uid=uid, status=403)
    r = await h.client.get(BETH_ACCESS)
    assert r.status_code == 401
    # Nothing changed for Beth.
    assert dsat(await get(h, BETH_ACCESS))["granted"] is False
    assert audit_docs(h, BETH) == []
    # Unknown student and unknown course: 404. Reason is required.
    await get(h, "/api/admin/students/stu_nobody/access", status=404)
    await grant(h, sid="stu_nobody", status=404)
    await grant(h, course="no_such_course", status=404)
    r = await h.client.post(
        f"{BETH_ACCESS}/grant", json={"courseId": "dsat", "reason": "  "}, headers=h.cmd(ADMIN)
    )
    assert r.status_code == 400
    # An admin is not a student and has no learning permissions.
    await get(h, "/api/twin", ADMIN, status=403)
    admin_ctx = ActorContext.for_admin(ADMIN, BETH)
    with pytest.raises(DomainError) as exc:
        await h.services.tasks.get_task(admin_ctx, "task_alex_dsat_01")
    assert exc.value.code is ErrorCode.FORBIDDEN


async def test_the_admin_view_shows_access_enrollments_and_audit_only(h: Harness) -> None:
    view = await get(h, BETH_ACCESS)
    assert view["studentId"] == BETH and view["displayName"]
    assert view["access"]["apCourses"] == ["calc_bc"] and view["access"]["courses"] == []
    calc = next(c for c in view["courses"] if c["courseId"] == "calc_bc")
    assert calc["granted"] and calc["enrollment"]["status"] == "active"
    assert dsat(view) | {"enrollment": None} == {
        "courseId": "dsat", "name": "Digital SAT", "category": "SAT",
        "availability": "active", "granted": False, "enrollment": None,
    }  # fmt: skip
    assert view["audit"] == []
    text = str(view)
    for private in ("mastery", "answer", "message", "assessment", "taskId", "sessionId"):
        assert private not in text


async def test_grant_then_enroll_with_one_audit_entry_and_a_filtered_event(h: Harness) -> None:
    r = await h.client.post("/api/courses/enroll", json={"courseId": "dsat"}, headers=h.cmd(BETH))
    assert r.status_code == 403 and r.json()["error"]["code"] == "COURSE_ACCESS_REQUIRED"

    out = await grant(h)
    assert out["changed"] is True and out["auditId"]
    assert out["access"]["access"]["courses"] == ["dsat"]
    assert out["access"]["access"]["apCourses"] == ["calc_bc"]  # untouched
    assert out["access"]["access"]["updatedBy"] == ADMIN
    assert dsat(out["access"])["granted"] is True
    [entry] = out["access"]["audit"]
    assert entry | {"at": None} == {
        "auditId": out["auditId"], "courseId": "dsat", "change": "grant",
        "reason": REASON, "actorId": ADMIN, "at": None,
    }  # fmt: skip

    stored = doc(h, f"students/{BETH}/access/current")
    assert stored is not None and stored["courses"] == ["dsat"] and stored["updatedBy"] == ADMIN
    assert len(audit_docs(h, BETH)) == 1
    [event] = await events(h, BETH, "access.changed")
    assert event["payload"] == {"courseId": "dsat", "change": "granted"}  # no admin, no reason
    assert ADMIN not in str(event) and REASON not in str(event)

    assert (await get(h, "/api/me/entitlements", BETH))["courses"] == ["dsat"]
    r = await h.client.post("/api/courses/enroll", json={"courseId": "dsat"}, headers=h.cmd(BETH))
    assert r.status_code == 200, r.text
    assert dsat(await get(h, BETH_ACCESS))["enrollment"]["status"] == "active"

    # Granting again changes nothing and writes nothing.
    again = await grant(h)
    assert again["changed"] is False and again["auditId"] is None
    assert len(audit_docs(h, BETH)) == 1
    assert len(await events(h, BETH, "access.changed")) == 1


async def test_ap_courses_are_stored_in_ap_courses(h: Harness) -> None:
    await revoke(h, course="calc_bc")
    assert (await get(h, BETH_ACCESS))["access"]["apCourses"] == []
    out = await grant(h, course="calc_bc")
    assert out["access"]["access"]["apCourses"] == ["calc_bc"]
    assert out["access"]["access"]["courses"] == []
    assert [a["change"] for a in out["access"]["audit"]] == ["grant", "revoke"]  # newest first


async def test_commands_are_idempotent(h: Harness) -> None:
    key = idem()
    first = await grant(h, key=key)
    r = await h.client.post(
        f"{BETH_ACCESS}/grant", json={"courseId": "dsat", "reason": REASON},
        headers=h.cmd(ADMIN, key),
    )  # fmt: skip
    assert r.status_code == 200 and r.headers.get("Idempotency-Replayed") == "true"
    assert r.json()["auditId"] == first["auditId"] and r.json()["changed"] is True
    assert len(audit_docs(h, BETH)) == 1
    r = await h.client.post(
        f"{BETH_ACCESS}/grant", json={"courseId": "dsat", "reason": "different"},
        headers=h.cmd(ADMIN, key),
    )  # fmt: skip
    assert r.status_code == 409 and r.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    r = await h.client.post(
        f"{BETH_ACCESS}/grant", json={"courseId": "dsat", "reason": REASON},
        headers=h.auth(ADMIN),
    )  # fmt: skip
    assert r.status_code == 400


async def test_revoke_blocks_new_work_and_keeps_every_record(h: Harness) -> None:
    await grant(h)
    r = await h.client.post("/api/courses/enroll", json={"courseId": "dsat"}, headers=h.cmd(BETH))
    assert r.status_code == 200
    tasks = [t for t in (await get(h, "/api/tasks", BETH))["tasks"] if t["courseId"] == "dsat"]
    equiv = next(t for t in tasks if t["questionId"] == "q_dsat_equiv_001")
    other = next(t for t in tasks if t["questionId"] != "q_dsat_equiv_001")

    # One finished set (a past result) and one session left open.
    s = await post(h, "/api/sessions", {"taskId": equiv["taskId"]}, uid=BETH, status=201)
    body = {"questionId": "q_dsat_equiv_001", "questionVersion": "1",
            "answer": {"text": "1: A\n2: C\n3: B", "fileIds": []}}  # fmt: skip
    await post(h, f"/api/sessions/{s['sessionId']}/submissions", body, uid=BETH, status=202)
    await h.settle()
    await post(h, f"/api/sessions/{s['sessionId']}/complete", {}, uid=BETH)
    open_s = await post(h, "/api/sessions", {"taskId": other["taskId"]}, uid=BETH, status=201)
    mastery_before = await get(h, "/api/mastery?courseId=dsat", BETH)

    out = await revoke(h)
    assert out["changed"] is True and dsat(out["access"])["granted"] is False
    assert dsat(out["access"])["enrollment"]["status"] == "active"  # enrollment kept

    # New work is refused.
    def refused(r: Any) -> bool:
        return r.status_code == 403 and r.json()["error"]["code"] == "COURSE_ACCESS_REQUIRED"

    sid = open_s["sessionId"]
    r = await h.client.post(
        f"/api/sessions/{sid}/messages", json={"text": "hint?"}, headers=h.cmd(BETH)
    )
    assert refused(r), r.text
    q = open_s["activity"]
    r = await h.client.post(
        f"/api/sessions/{sid}/submissions",
        json={"questionId": q["questionId"], "questionVersion": q["questionVersion"],
              "answer": {"text": "1: A", "fileIds": []}},
        headers=h.cmd(BETH),
    )  # fmt: skip
    assert refused(r), r.text
    await post(h, f"/api/sessions/{sid}/abandon", {}, uid=BETH)  # the open session can end
    r = await h.client.post("/api/sessions", json={"taskId": other["taskId"]}, headers=h.cmd(BETH))
    assert refused(r), r.text
    r = await h.client.post("/api/courses/enroll", json={"courseId": "dsat"}, headers=h.cmd(BETH))
    assert refused(r), r.text

    # Every record is still readable.
    assessments = await get(h, f"/api/assessments?sessionId={s['sessionId']}", BETH)
    assert assessments["assessments"][0]["status"] == "accepted"
    assert await get(h, "/api/mastery?courseId=dsat", BETH) == mastery_before
    still = [t["taskId"] for t in (await get(h, "/api/tasks", BETH))["tasks"]]
    assert equiv["taskId"] in still and other["taskId"] in still
    # No practice is added for a course the student cannot access.
    await post(h, "/api/plans/replan", {}, uid=BETH, status=202)
    await h.settle()
    after = [t for t in (await get(h, "/api/tasks", BETH))["tasks"] if t["courseId"] == "dsat"]
    assert len(after) == len(tasks)

    changes = [(e["payload"]["change"]) for e in await events(h, BETH, "access.changed")]
    assert changes == ["granted", "revoked"]
    audit = (await get(h, BETH_ACCESS))["audit"]
    assert [(a["change"], a["reason"]) for a in audit] == [
        ("revoke", "Left the pilot."),
        ("grant", REASON),
    ]


async def test_a_failed_commit_leaves_neither_record_nor_audit(h: Harness) -> None:
    admin = PlatformActor.for_member(ADMIN, ActorRole.ADMIN, None)
    await h.services.content_sync.ensure_fresh()  # authored courses, as the route does
    cmd = CommandKey(scope="test grant", key=idem(), request_digest="d")
    before = doc(h, f"students/{BETH}/access/current")
    seq_before = doc(h, f"students/{BETH}/eventState/current")
    h.store.fail_next_commits = 1
    with pytest.raises(SimulatedCommitFailure):
        await h.services.access.change(admin, BETH, "dsat", AccessChange.GRANT, REASON, cmd)
    assert doc(h, f"students/{BETH}/access/current") == before
    assert doc(h, f"students/{BETH}/eventState/current") == seq_before
    assert audit_docs(h, BETH) == []
    # The retry (same key) commits everything once.
    out = await h.services.access.change(admin, BETH, "dsat", AccessChange.GRANT, REASON, cmd)
    assert out.value.changed and len(audit_docs(h, BETH)) == 1


async def test_bulk_grant_reports_each_student_and_retries_only_failures(h: Harness) -> None:
    key = idem()
    body = {"studentIds": [BETH, "stu_nobody", ALEX, BETH], "courseId": "dsat",
            "change": "grant", "reason": "Fall cohort."}  # fmt: skip
    out = await post(h, "/api/admin/access/bulk", body, key=key)
    by = {r["studentId"]: r for r in out["results"]}
    assert [r["studentId"] for r in out["results"]] == [BETH, "stu_nobody", ALEX]
    assert by[BETH]["status"] == "changed" and by[BETH]["auditId"]
    assert by["stu_nobody"] | {"message": None} == {
        "studentId": "stu_nobody", "status": "failed", "auditId": None,
        "errorCode": "NOT_FOUND", "message": None,
    }  # fmt: skip
    assert by[ALEX]["status"] == "unchanged"  # Alex already has Digital SAT
    assert (out["changed"], out["unchanged"], out["failed"]) == (1, 1, 1)
    assert len(audit_docs(h, BETH)) == 1 and audit_docs(h, ALEX) == []

    again = await post(h, "/api/admin/access/bulk", body, key=key)
    assert {r["studentId"]: r["auditId"] for r in again["results"]} == {
        r["studentId"]: r["auditId"] for r in out["results"]
    }
    assert len(audit_docs(h, BETH)) == 1


async def test_one_students_change_never_touches_another(h: Harness) -> None:
    alex_access = doc(h, f"students/{ALEX}/access/current")
    alex_events = await events(h, ALEX, "access.changed")
    await grant(h)
    await revoke(h, course="calc_bc")
    assert doc(h, f"students/{ALEX}/access/current") == alex_access
    assert await events(h, ALEX, "access.changed") == alex_events == []
    assert audit_docs(h, ALEX) == []
    assert (await get(h, f"/api/admin/students/{ALEX}/access"))["audit"] == []
