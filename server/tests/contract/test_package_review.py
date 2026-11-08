"""Step 26: author role, review gate and publishing.

A course reaches students only as upload → validator report → submit → platform
reviewer approval → activation, and every step is audited. Authors see only their own
organization's packages, cannot grant access, and never see student data. A new version
never changes an open session; retiring stops new work without deleting records.

The test course `alglab` is the Digital SAT package with its ids renamed: a second,
independent course built from data only.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from app.adapters.runtime import RandomIdFactory
from app.bootstrap import build_services
from app.registries.content import DEFAULT_CONTENT_ROOT
from tests.support import Harness, build_harness, harness_settings, idem

ALEX, BETH = "stu_alex", "stu_beth"
AUTHOR, OTHER_AUTHOR, REVIEWER = "author_hsos", "author_sample", "reviewer_platform"
DSAT = json.loads((DEFAULT_CONTENT_ROOT / "authored/dsat/package.json").read_text())
COURSE = "alglab"
PKG = json.loads(json.dumps(DSAT).replace("dsat", COURSE))
BASE = f"/api/authoring/packages/{COURSE}/versions"
REVIEW = f"/api/review/packages/{COURSE}/versions"
PUBLICATION = REVIEW.replace("/api/review/", "/api/admin/")
APPROVE = {"notes": "Checked evaluation and license.", "licenseAttested": True}


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch) -> Harness:
    return build_harness(clean_env)


def package(version: str = "1.0.0", **manifest: Any) -> dict[str, Any]:
    pkg = copy.deepcopy(PKG)
    pkg["manifest"].update(version=version, **manifest)
    return pkg


async def post(
    h: Harness, path: str, uid: str, body: dict[str, Any], status: int, key: str | None = None
) -> Any:
    r = await h.client.post(path, json=body, headers=h.cmd(uid, key))
    assert r.status_code == status, r.text
    return r.json()


async def get(h: Harness, path: str, uid: str, status: int = 200) -> Any:
    r = await h.client.get(path, headers=h.auth(uid))
    assert r.status_code == status, r.text
    return r.json()


async def upload(h: Harness, pkg: dict[str, Any], uid: str = AUTHOR, status: int = 201) -> Any:
    return await post(h, "/api/authoring/packages", uid, {"package": pkg}, status)


async def publish(h: Harness, version: str = "1.0.0", pkg: dict[str, Any] | None = None) -> Any:
    """The whole gate: upload, submit, approve, activate."""
    await upload(h, pkg or package(version))
    await post(h, f"{BASE}/{version}/submit", AUTHOR, {}, 200)
    await post(h, f"{REVIEW}/{version}/approve", REVIEWER, APPROVE, 200)
    return await post(
        h,
        f"{PUBLICATION}/{version}/activate",
        "admin_platform",
        {},
        200,
    )


def grant(h: Harness, sid: str, *courses: str) -> None:
    """Platform-managed access (an admin action; authors have no way to do this)."""
    h.put_doc(
        f"students/{sid}/access/current",
        {"apCourses": ["calc_bc"], "courses": list(courses), "admissions": False,
         "updatedAt": h.clock.now(), "updatedBy": "admin-test"},
    )  # fmt: skip


async def catalog_ids(h: Harness, sid: str = ALEX) -> set[str]:
    return {c["courseId"] for c in (await get(h, "/api/courses/catalog", sid))["courses"]}


async def enroll(h: Harness, sid: str = ALEX, course: str = COURSE) -> int:
    r = await h.client.post("/api/courses/enroll", json={"courseId": course}, headers=h.cmd(sid))
    return r.status_code


async def course_tasks(h: Harness, sid: str = ALEX) -> list[dict[str, Any]]:
    tasks = (await get(h, "/api/tasks", sid))["tasks"]
    return [t for t in tasks if t["courseId"] == COURSE]


async def test_only_a_reviewed_and_activated_package_reaches_students(h: Harness) -> None:
    draft = await upload(h, package())
    assert draft["status"] == "draft" and draft["orgId"] == "org_hsos_content"
    assert draft["report"]["valid"] and draft["report"]["evaluation"]["autoPassed"] == 12
    assert COURSE not in await catalog_ids(h)

    await post(h, f"{BASE}/1.0.0/submit", AUTHOR, {}, 200)
    assert COURSE not in await catalog_ids(h)
    queue = await get(h, "/api/review/packages", REVIEWER)
    # The seeded APUSH package (Step 34.3) waits in the same queue.
    assert [(v["courseId"], v["status"]) for v in queue["versions"]] == [
        (COURSE, "submitted"),
        ("apush", "submitted"),
    ]

    approved = await post(h, f"{REVIEW}/1.0.0/approve", REVIEWER, APPROVE, 200)
    assert approved["review"]["reviewerId"] == REVIEWER and approved["review"]["licenseAttested"]
    assert COURSE not in await catalog_ids(h)  # approved is not active
    assert await enroll(h) == 404

    active = await post(
        h,
        f"{PUBLICATION}/1.0.0/activate",
        "admin_platform",
        {},
        200,
    )
    assert active["status"] == "active"
    # Every transition is audited: who, from, to.
    assert [(c["fromStatus"], c["toStatus"], c["actorId"]) for c in active["history"]] == [
        (None, "draft", AUTHOR),
        ("draft", "submitted", AUTHOR),
        ("submitted", "approved", REVIEWER),
        ("approved", "active", "admin_platform"),
    ]
    assert COURSE in await catalog_ids(h)

    # Admin publication opens enrollment without individual grants.
    assert await enroll(h) == 200
    starters = await course_tasks(h)
    assert sorted(t["questionId"] for t in starters) == [
        "q_alglab_equiv_001",
        "q_alglab_nonlin_001",
    ]
    assert all(t["reason"]["code"] == "INITIAL_PRACTICE" for t in starters)

    # Re-enrolling never duplicates starter tasks.
    await post(h, "/api/courses/unenroll", ALEX, {"courseId": COURSE}, 200)
    assert await enroll(h) == 200
    assert len(await course_tasks(h)) == 2


async def test_organizations_are_isolated(h: Harness) -> None:
    await upload(h, package())
    await get(h, f"{BASE}/1.0.0", OTHER_AUTHOR, status=404)
    assert (await get(h, "/api/authoring/packages", OTHER_AUTHOR))["versions"] == []
    r = await h.client.post(f"{BASE}/1.0.0/submit", json={}, headers=h.cmd(OTHER_AUTHOR))
    assert r.status_code == 404
    # A courseId owned by another organization, or a bundled course, cannot be claimed.
    taken = await upload(h, package("2.0.0"), OTHER_AUTHOR, 409)
    assert taken["error"]["code"] == "COURSE_ID_TAKEN"
    calc = json.loads(json.dumps(PKG).replace(COURSE, "calc_bc"))
    assert (await upload(h, calc, OTHER_AUTHOR, 409))["error"]["code"] == "COURSE_ID_TAKEN"
    # The seeded Digital SAT package belongs to org_hsos_content.
    assert (await upload(h, DSAT, OTHER_AUTHOR, 409))["error"]["code"] == "COURSE_ID_TAKEN"
    own = await get(h, f"{BASE}/1.0.0", AUTHOR)
    assert own["package"]["manifest"]["courseId"] == COURSE


async def test_roles_are_enforced(h: Harness) -> None:
    # Students cannot reach authoring or review routes; authors cannot review; reviewers
    # cannot author; platform members have no student record.
    assert (await upload(h, package(), ALEX, 403))["error"]["code"] == "FORBIDDEN"
    await get(h, "/api/review/packages", ALEX, status=403)
    await get(h, "/api/review/packages", AUTHOR, status=403)
    await upload(h, package(), REVIEWER, 403)
    await upload(h, package())
    await post(h, f"{BASE}/1.0.0/submit", AUTHOR, {}, 200)
    await post(h, f"{REVIEW}/1.0.0/approve", AUTHOR, APPROVE, 403)
    await get(h, "/api/tasks", AUTHOR, status=403)
    await get(h, "/api/twin", REVIEWER, status=403)
    r = await h.client.get("/api/authoring/packages")
    assert r.status_code == 401
    # Drafts stay private to their organization, reviewers included.
    await upload(h, package("1.1.0"))
    await get(h, f"{REVIEW}/1.1.0", REVIEWER, status=404)


async def test_an_invalid_package_is_reported_and_cannot_be_submitted(h: Harness) -> None:
    bad = package()
    bad["questions"][0]["skillIds"] = ["calc_bc.chain-rule"]
    del bad["manifest"]["license"]
    draft = await upload(h, bad)
    assert not draft["report"]["valid"]
    assert {e["path"] for e in draft["report"]["errors"]} == {"manifest.license"}
    err = await post(h, f"{BASE}/1.0.0/submit", AUTHOR, {}, 409)
    assert err["error"]["code"] == "PACKAGE_INVALID"
    # Fix the schema error: the cross-course skill reference is reported next, with a path.
    del bad["questions"][0]["skillIds"]
    bad["manifest"]["license"] = "Original work"
    bad["questions"][0]["skillIds"] = ["calc_bc.chain-rule"]
    again = await upload(h, bad, status=200)  # a draft may be replaced
    assert [e["path"] for e in again["report"]["errors"]] == [
        f"questions[{bad['questions'][0]['questionId']}].skillIds"
    ]
    # Without courseId/version there is nothing to store.
    nameless = package()
    del nameless["manifest"]["courseId"]
    r = await upload(h, nameless, status=400)
    assert (
        r["error"]["code"] == "VALIDATION_FAILED" and "manifest.courseId" in r["error"]["message"]
    )


async def test_approval_needs_attestations_and_a_passing_evaluation_set(h: Harness) -> None:
    pkg = package()
    case = pkg["evaluationSet"][0]
    case["expectedEarned"] = {k: 0 for k in case["expectedEarned"]}  # a wrong expectation
    await upload(h, pkg)
    await post(h, f"{BASE}/1.0.0/submit", AUTHOR, {}, 200)
    err = await post(h, f"{REVIEW}/1.0.0/approve", REVIEWER, APPROVE, 409)
    assert err["error"]["code"] == "REVIEW_REQUIREMENTS_NOT_MET"
    assert case["caseId"] in err["error"]["message"]

    await upload(h, package("1.0.1"))
    await post(h, f"{BASE}/1.0.1/submit", AUTHOR, {}, 200)
    no_license = {**APPROVE, "licenseAttested": False}
    err = await post(h, f"{REVIEW}/1.0.1/approve", REVIEWER, no_license, 409)
    assert "license" in err["error"]["message"]
    # An approved-but-not-activated version cannot be activated before approval either.
    err = await post(
        h,
        f"{PUBLICATION}/1.0.1/activate",
        "admin_platform",
        {},
        409,
    )
    assert err["error"]["code"] == "INVALID_STATE_TRANSITION"


async def test_rejection_is_recorded_and_released_versions_are_immutable(h: Harness) -> None:
    await upload(h, package())
    await post(h, f"{BASE}/1.0.0/submit", AUTHOR, {}, 200)
    notes = {"notes": "Item 2 of the second set has two defensible answers."}
    rejected = await post(h, f"{REVIEW}/1.0.0/reject", REVIEWER, notes, 200)
    assert rejected["status"] == "rejected"
    own = await get(h, f"{BASE}/1.0.0", AUTHOR)
    assert own["review"]["decision"] == "rejected" and own["review"]["notes"] == notes["notes"]
    # A submitted or rejected version cannot be re-uploaded, and versions only go up.
    err = await upload(h, package(), status=409)
    assert err["error"]["code"] == "PACKAGE_VERSION_EXISTS"
    assert (await upload(h, package("0.9.0"), status=409))["error"][
        "code"
    ] == "PACKAGE_VERSION_EXISTS"
    await post(h, f"{REVIEW}/1.0.0/approve", REVIEWER, APPROVE, 409)  # rejected is final
    assert (await upload(h, package("1.0.1")))["status"] == "draft"


async def test_commands_are_idempotent(h: Harness) -> None:
    await upload(h, package())
    key = idem()
    first = await post(h, f"{BASE}/1.0.0/submit", AUTHOR, {}, 200, key)
    r = await h.client.post(f"{BASE}/1.0.0/submit", json={}, headers=h.cmd(AUTHOR, key))
    assert r.status_code == 200 and r.headers.get("Idempotency-Replayed") == "true"
    assert r.json() == first
    # Same key, different request → conflict, not a second effect.
    r = await h.client.post(
        f"{REVIEW}/1.0.0/approve", json=APPROVE, headers=h.cmd(REVIEWER, "k" * 20)
    )
    assert r.status_code == 200
    r = await h.client.post(
        f"{REVIEW}/1.0.0/approve", json={**APPROVE, "notes": "x"}, headers=h.cmd(REVIEWER, "k" * 20)
    )
    assert r.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    upload_key = idem()
    a = await post(
        h, "/api/authoring/packages", AUTHOR, {"package": package("1.1.0")}, 201, upload_key
    )
    b = await post(
        h, "/api/authoring/packages", AUTHOR, {"package": package("1.1.0")}, 201, upload_key
    )
    assert a == b


async def start(h: Harness, task_id: str, sid: str = ALEX) -> dict[str, Any]:
    return dict(await post(h, "/api/sessions", sid, {"taskId": task_id}, 201))


async def submit(h: Harness, session: dict[str, Any], text: str, status: int = 202) -> Any:
    act = session["activity"]
    body = {"questionId": act["questionId"], "questionVersion": act["questionVersion"],
            "answer": {"text": text, "fileIds": []}}  # fmt: skip
    out = await post(h, f"/api/sessions/{session['sessionId']}/submissions", ALEX, body, status)
    await h.settle()
    return out


async def assessments(h: Harness, session_id: str) -> list[dict[str, Any]]:
    return list((await get(h, f"/api/assessments?sessionId={session_id}", ALEX))["assessments"])


async def test_a_new_version_never_changes_an_open_session(h: Harness) -> None:
    await publish(h, "1.0.0")
    grant(h, ALEX, "dsat", COURSE)
    assert await enroll(h) == 200
    t_equiv, t_nonlin = sorted(await course_tasks(h), key=lambda t: t["questionId"])
    old = await start(h, t_equiv["taskId"])
    assert old["contextVersion"]["pack"] == "1.0.0"

    # Version 1.1.0 rewrites item 1 of the first set and moves its key from A to D.
    v2 = package("1.1.0")
    q = next(x for x in v2["questions"] if x["questionId"] == "q_alglab_equiv_001")
    q["items"][0]["prompt"] = "Rewritten item 1."
    q["items"][0]["answerKey"] = "D"
    for c in v2["evaluationSet"]:
        if c["questionId"] == q["questionId"] and c["expectedStatus"] == "accepted":
            c["answerText"] = c["answerText"].replace("1: A", "1: D").replace("1) B", "1) A")
    await publish(h, "1.1.0", v2)
    v1 = await get(h, f"{BASE}/1.0.0", AUTHOR)
    assert v1["status"] == "superseded"

    # The open session still shows and scores 1.0.0: A is correct for item 1 there.
    same = await get(h, f"/api/sessions/{old['sessionId']}", ALEX)
    assert same["contextVersion"]["pack"] == "1.0.0"
    assert same["activity"]["items"][0]["prompt"] != "Rewritten item 1."
    await submit(h, same, "1: A\n2: C\n3: B")
    [a] = await assessments(h, old["sessionId"])
    assert a["status"] == "accepted" and [r["earned"] for r in a["rubricResults"]] == [1, 1, 1]

    # A session started now pins 1.1.0. The past assessment is unchanged.
    new = await start(h, t_nonlin["taskId"])
    assert new["contextVersion"]["pack"] == "1.1.0"
    assert await assessments(h, old["sessionId"]) == [a]
    # An older version can never replace the active one.
    err = await post(
        h,
        f"{PUBLICATION}/1.0.0/activate",
        "admin_platform",
        {},
        409,
    )
    assert err["error"]["code"] == "INVALID_STATE_TRANSITION"


async def test_retiring_stops_new_work_and_keeps_records(h: Harness) -> None:
    await publish(h)
    grant(h, ALEX, "dsat", COURSE)
    assert await enroll(h) == 200
    first, second = sorted(await course_tasks(h), key=lambda t: t["questionId"])  # equiv, nonlin
    done = await start(h, first["taskId"])
    await submit(h, done, "1: A\n2: C\n3: B")
    open_session = await start(h, second["taskId"])

    retired = await post(h, f"/api/admin/courses/{COURSE}/retire", "admin_platform",
                         {"notes": "Replaced by a new course."}, 200)  # fmt: skip
    assert retired["status"] == "retired"
    assert COURSE not in await catalog_ids(h)
    course = await get(h, f"/api/courses/{COURSE}", ALEX)
    assert course["availability"] == "retired"

    # No new work: no submissions in the open session, no new sessions or enrollments.
    err = await submit(h, open_session, "1: A", status=409)
    assert err["error"]["code"] == "COURSE_NOT_AVAILABLE"
    assert await enroll(h, BETH) in (403, 409)
    # Records stay: sessions, assessments and mastery are still readable.
    assert (await get(h, f"/api/sessions/{open_session['sessionId']}", ALEX))["activity"]
    assert await assessments(h, done["sessionId"])
    mastery = await get(h, f"/api/mastery?courseId={COURSE}", ALEX)
    assert any(m["evidenceCount"] for m in mastery["mastery"])
    abandoned = await post(h, f"/api/sessions/{open_session['sessionId']}/abandon", ALEX, {}, 200)
    assert abandoned["status"] == "ABANDONED"


async def test_authors_never_see_student_data(h: Harness) -> None:
    await publish(h)
    grant(h, ALEX, "dsat", COURSE)
    assert await enroll(h) == 200
    views = [
        await get(h, "/api/authoring/packages", AUTHOR),
        await get(h, f"{BASE}/1.0.0", AUTHOR),
        await get(h, f"{REVIEW}/1.0.0", REVIEWER),
    ]
    text = json.dumps(views)
    assert ALEX not in text and "students/" not in text


async def test_a_worker_with_a_stale_copy_runs_a_just_activated_course(
    clean_env: pytest.MonkeyPatch,
) -> None:
    # Found in staging 2026-11-07: the worker instance had refreshed its packages seconds
    # before an activation, so for up to 30 s it did not know the course and failed the
    # Run permanently with SESSION_NOT_OPEN. A Run pinned to an unloaded version must
    # reload first.
    h = build_harness(clean_env)
    worker = build_services(
        harness_settings(clean_env), store=h.store, clock=h.clock, ids=RandomIdFactory(),
        queue=h.queue, worker_id="worker-stale",
    )  # fmt: skip
    await worker.content_sync.refresh()  # loaded just now, before the course exists

    await publish(h)
    grant(h, ALEX, "dsat", COURSE)
    assert await enroll(h) == 200
    task = sorted(await course_tasks(h), key=lambda t: t["questionId"])[0]
    session = await start(h, task["taskId"])
    act = session["activity"]
    body = {"questionId": act["questionId"], "questionVersion": act["questionVersion"],
            "answer": {"text": "1: A\n2: C\n3: B", "fileIds": []}}  # fmt: skip
    run_id = (await post(h, f"/api/sessions/{session['sessionId']}/submissions", ALEX, body, 202))[
        "runId"
    ]

    # Deliver to the stale worker instance instead of the harness's own.
    await h.services.dispatcher.dispatch_pending()
    assert await h.queue.drain(worker.deliveries.process) == 1
    run = await get(h, f"/api/runs/{run_id}", ALEX)
    assert run["status"] == "SUCCEEDED", run
    [a] = await assessments(h, session["sessionId"])
    assert a["status"] == "accepted"
