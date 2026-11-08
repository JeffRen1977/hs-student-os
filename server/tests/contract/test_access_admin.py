"""Admin publication follows reviewer approval and opens enrollment to every student."""

from __future__ import annotations

import pytest

from app.adapters.firestore.memory_store import SimulatedCommitFailure
from app.domain.commands import CommandKey
from app.domain.types.actor import ActorRole, PlatformActor
from tests.contract.test_package_review import (
    APPROVE,
    AUTHOR,
    BASE,
    COURSE,
    REVIEW,
    REVIEWER,
    get,
    package,
    post,
    upload,
)
from tests.support import Harness, build_harness, idem

ADMIN = "admin_platform"
PUBLISH = f"/api/admin/packages/{COURSE}/versions/1.0.0/activate"


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch) -> Harness:
    return build_harness(clean_env)


async def approved(h: Harness) -> None:
    await upload(h, package())
    await post(h, f"{BASE}/1.0.0/submit", AUTHOR, {}, 200)
    await post(h, f"{REVIEW}/1.0.0/approve", REVIEWER, APPROVE, 200)


async def test_publication_is_admin_only_and_review_is_reviewer_only(h: Harness) -> None:
    await approved(h)
    for uid in (AUTHOR, REVIEWER, "stu_alex", "stu_beth", "parent_alex"):
        await get(h, "/api/admin/packages", uid, 403)
        await post(h, PUBLISH, uid, {}, 403)
        await post(h, f"/api/admin/courses/{COURSE}/retire", uid, {"notes": "x"}, 403)
    await post(h, f"{REVIEW}/1.0.0/approve", ADMIN, APPROVE, 403)
    await get(h, "/api/twin", ADMIN, 403)
    assert (await h.client.get("/api/admin/packages")).status_code == 401
    await post(h, f"{REVIEW}/1.0.0/activate", REVIEWER, {}, 404)
    # The obsolete per-student and cohort grants no longer exist.
    for path in ("/api/admin/students/stu_beth/access/grant", "/api/admin/access/bulk"):
        await post(h, path, ADMIN, {}, 404)


async def test_only_reviewed_versions_can_be_published(h: Harness) -> None:
    await upload(h, package())
    await post(h, PUBLISH, ADMIN, {}, 404)  # private draft
    await post(h, f"{BASE}/1.0.0/submit", AUTHOR, {}, 200)
    out = await post(h, PUBLISH, ADMIN, {}, 409)
    assert out["error"]["code"] == "INVALID_STATE_TRANSITION"
    await post(h, f"{REVIEW}/1.0.0/reject", REVIEWER, {"notes": "Bad key."}, 200)
    await post(h, PUBLISH, ADMIN, {}, 409)
    queue = await get(h, "/api/admin/packages", ADMIN)
    assert COURSE not in {v["courseId"] for v in queue["versions"]}


async def test_admin_publication_opens_course_to_all_without_student_writes(h: Harness) -> None:
    await approved(h)
    queue = await get(h, "/api/admin/packages", ADMIN)
    v = next(v for v in queue["versions"] if v["courseId"] == COURSE)
    assert v["status"] == "approved" and v["review"]["reviewerId"] == REVIEWER
    assert v["package"] is None
    before = {p: d for p, d in h.store.snapshot().items() if p.startswith("students/")}
    active = await post(h, PUBLISH, ADMIN, {}, 200)
    assert active["history"][-1]["actorId"] == ADMIN
    assert active["review"]["reviewerId"] == REVIEWER
    assert {p: d for p, d in h.store.snapshot().items() if p.startswith("students/")} == before
    for sid in ("stu_alex", "stu_beth"):
        assert COURSE not in before[f"students/{sid}/access/current"].get("courses", [])
        catalog = await get(h, "/api/courses/catalog", sid)
        entry = next(c for c in catalog["courses"] if c["courseId"] == COURSE)
        assert entry["entitled"] and entry["status"] == "available"
        assert not entry["enrolled"]
        await post(h, "/api/courses/enroll", sid, {"courseId": COURSE}, 200)
        tasks = await get(h, "/api/tasks", sid)
        task = next(t for t in tasks["tasks"] if t["courseId"] == COURSE)
        await post(h, "/api/sessions", sid, {"taskId": task["taskId"]}, 201)


async def test_publish_retry_is_idempotent_and_key_required(h: Harness) -> None:
    await approved(h)
    key = idem()
    first = await post(h, PUBLISH, ADMIN, {}, 200, key)
    r = await h.client.post(PUBLISH, json={}, headers=h.cmd(ADMIN, key))
    assert r.status_code == 200 and r.headers["Idempotency-Replayed"] == "true"
    assert r.json() == first
    assert len([x for x in r.json()["history"] if x["toStatus"] == "active"]) == 1
    r = await h.client.post(PUBLISH, json={}, headers=h.auth(ADMIN))
    assert r.status_code == 400


async def test_failed_publication_commits_neither_active_pointer_nor_audit(h: Harness) -> None:
    await approved(h)
    actor = PlatformActor.for_member(ADMIN, ActorRole.ADMIN, None)
    cmd = CommandKey(scope="publish", key=idem(), request_digest="d")
    before = h.store.snapshot()
    h.store.fail_next_commits = 1
    with pytest.raises(SimulatedCommitFailure):
        await h.services.packages.activate(actor, COURSE, "1.0.0", cmd)
    assert h.store.snapshot() == before
    out = await h.services.packages.activate(actor, COURSE, "1.0.0", cmd)
    assert out.value.status.value == "active"


async def test_retirement_blocks_everyone_but_preserves_records(h: Harness) -> None:
    await approved(h)
    await post(h, PUBLISH, ADMIN, {}, 200)
    sessions = []
    for sid in ("stu_alex", "stu_beth"):
        await post(h, "/api/courses/enroll", sid, {"courseId": COURSE}, 200)
        tasks = await get(h, "/api/tasks", sid)
        task = next(t for t in tasks["tasks"] if t["courseId"] == COURSE)
        session = await post(h, "/api/sessions", sid, {"taskId": task["taskId"]}, 201)
        sessions.append((sid, session["sessionId"]))
    await post(
        h, f"/api/admin/courses/{COURSE}/retire", ADMIN, {"notes": "Content correction."}, 200
    )
    for sid, session_id in sessions:
        r = await post(h, "/api/courses/enroll", sid, {"courseId": COURSE}, 409)
        assert r["error"]["code"] == "COURSE_NOT_AVAILABLE"
        await post(h, f"/api/sessions/{session_id}/messages", sid, {"text": "hint?"}, 409)
        assert (await get(h, f"/api/sessions/{session_id}", sid))["sessionId"] == session_id
        await post(h, f"/api/sessions/{session_id}/abandon", sid, {}, 200)


async def test_queued_work_rechecks_publication_before_execution(h: Harness) -> None:
    await approved(h)
    await post(h, PUBLISH, ADMIN, {}, 200)
    sid = "stu_beth"
    await post(h, "/api/courses/enroll", sid, {"courseId": COURSE}, 200)
    tasks = await get(h, "/api/tasks", sid)
    task = next(t for t in tasks["tasks"] if t["courseId"] == COURSE)
    session = await post(h, "/api/sessions", sid, {"taskId": task["taskId"]}, 201)
    queued = await post(
        h, f"/api/sessions/{session['sessionId']}/messages", sid, {"text": "Please help."}, 202
    )
    await post(h, f"/api/admin/courses/{COURSE}/retire", ADMIN, {"notes": "Correction."}, 200)
    await h.settle()
    run = await get(h, f"/api/runs/{queued['runId']}", sid)
    assert run["status"] == "FAILED"
    assert run["error"]["code"] == "COURSE_NOT_AVAILABLE"
