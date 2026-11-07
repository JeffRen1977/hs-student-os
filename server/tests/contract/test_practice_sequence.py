"""Practice top-up (BACKEND.md §9, COURSE_PACKAGE.md `practiceSequence`, 2026-11-07).

Found on staging: students only ever got a course's starter tasks, so 10 of Digital SAT
2.0.0's 12 sets never reached anyone. A package's practice order (starter tasks, then the
practice sequence) now keeps each enrolled student at two unfinished tasks per course, in
the planning commit and when a session completes. Uses the real Digital SAT 2.0.1 package.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from app.registries.content import DEFAULT_CONTENT_ROOT
from app.registries.package_validator import validate_package
from tests.support import Harness, build_harness

ALEX, BETH = "stu_alex", "stu_beth"
AUTHOR, REVIEWER = "author_hsos", "reviewer_platform"
PKG = json.loads((DEFAULT_CONTENT_ROOT / "authored/dsat/package-2.0.1.json").read_text())
ORDER = [t["questionId"] for t in PKG["starterTasks"] + PKG["practiceSequence"]]
KEYS = {
    q["questionId"]: "\n".join(f"{i['itemId']}: {i['answerKey']}" for i in q["items"])
    for q in PKG["questions"]
}
BASE, REVIEW = "/api/authoring/packages/dsat/versions", "/api/review/packages/dsat/versions"


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch) -> Harness:
    return build_harness(clean_env)


async def post(h: Harness, path: str, uid: str, body: dict[str, Any], status: int = 200) -> Any:
    r = await h.client.post(path, json=body, headers=h.cmd(uid))
    assert r.status_code == status, r.text
    return r.json()


async def get(h: Harness, path: str, uid: str = BETH) -> Any:
    r = await h.client.get(path, headers=h.auth(uid))
    assert r.status_code == 200, r.text
    return r.json()


async def publish_2_0_1(h: Harness, pkg: dict[str, Any] | None = None) -> None:
    await post(h, "/api/authoring/packages", AUTHOR, {"package": pkg or PKG}, 201)
    await post(h, f"{BASE}/2.0.1/submit", AUTHOR, {})
    await post(h, f"{REVIEW}/2.0.1/approve", REVIEWER, {"notes": "ok", "licenseAttested": True})
    await post(h, f"{REVIEW}/2.0.1/activate", REVIEWER, {})


def grant(h: Harness, sid: str, *courses: str) -> None:
    h.put_doc(
        f"students/{sid}/access/current",
        {"apCourses": ["calc_bc"], "courses": list(courses), "admissions": False,
         "updatedAt": h.clock.now(), "updatedBy": "admin-test"},
    )  # fmt: skip


async def dsat_tasks(h: Harness, sid: str = BETH) -> list[dict[str, Any]]:
    return [t for t in (await get(h, "/api/tasks", sid))["tasks"] if t["courseId"] == "dsat"]


def open_ids(tasks: list[dict[str, Any]]) -> list[str]:
    return sorted(t["questionId"] for t in tasks if t["status"] in ("PLANNED", "IN_PROGRESS"))


async def finish(h: Harness, task: dict[str, Any], sid: str = BETH) -> None:
    """Start the task's set, answer every item correctly, complete the session."""
    s = await post(h, "/api/sessions", sid, {"taskId": task["taskId"]}, 201)
    act = s["activity"]
    body = {"questionId": act["questionId"], "questionVersion": act["questionVersion"],
            "answer": {"text": KEYS[act["questionId"]], "fileIds": []}}  # fmt: skip
    await post(h, f"/api/sessions/{s['sessionId']}/submissions", sid, body, 202)
    await h.settle()
    await post(h, f"/api/sessions/{s['sessionId']}/complete", sid, {})


async def skip(h: Harness, task: dict[str, Any], sid: str = BETH) -> None:
    r = await h.client.patch(
        f"/api/tasks/{task['taskId']}",
        json={"status": "SKIPPED", "skipReason": "no_time"},
        headers={**h.auth(sid), "If-Match": f'"{task["version"]}"'},
    )
    assert r.status_code == 200, r.text


async def replan(h: Harness, sid: str = BETH) -> dict[str, Any]:
    await post(h, "/api/plans/replan", sid, {}, 202)
    await h.settle()
    return dict(await get(h, "/api/plans/latest", sid))


async def enrolled_beth(h: Harness) -> None:
    await publish_2_0_1(h)
    grant(h, BETH, "dsat")
    await post(h, "/api/courses/enroll", BETH, {"courseId": "dsat"})


async def test_completing_a_set_offers_the_next_one_in_the_package_order(h: Harness) -> None:
    await enrolled_beth(h)
    tasks = await dsat_tasks(h)
    assert open_ids(tasks) == sorted(ORDER[:2])  # the two starter tasks
    alg = next(t for t in tasks if t["questionId"] == ORDER[1])
    await finish(h, alg)

    tasks = await dsat_tasks(h)
    assert open_ids(tasks) == sorted([ORDER[0], ORDER[2]])  # still two open: the next set
    nxt = next(t for t in tasks if t["questionId"] == ORDER[2])
    assert nxt["reason"]["code"] == "NEXT_PRACTICE" and nxt["status"] == "PLANNED"
    assert nxt["reason"]["explanation"].startswith("Next practice set in Digital SAT.")
    assert nxt["title"] == PKG["practiceSequence"][0]["title"]
    assert nxt["durationMin"] == PKG["practiceSequence"][0]["durationMin"]
    # Completing the same session again (idempotent replay) creates nothing more.
    assert len(await dsat_tasks(h)) == 3


async def test_planning_tops_up_and_plans_the_new_tasks_together(h: Harness) -> None:
    await enrolled_beth(h)
    starters = await dsat_tasks(h)
    await skip(h, starters[0])
    plan = await replan(h)
    tasks = await dsat_tasks(h)
    created = [t for t in tasks if t["reason"]["code"] == "NEXT_PRACTICE"]
    assert [t["questionId"] for t in created] == [ORDER[2]]
    assert created[0]["taskId"] in {e["taskId"] for e in plan["entries"]}
    # A skipped set is never offered again, and a second replan creates nothing new.
    await replan(h)
    assert len(await dsat_tasks(h)) == 3


async def test_the_whole_order_is_offered_once_then_nothing_more(h: Harness) -> None:
    await enrolled_beth(h)
    for _ in range(len(ORDER)):
        for t in await dsat_tasks(h):
            if t["status"] == "PLANNED":
                await skip(h, t)
        await replan(h)
    offered = [t["questionId"] for t in await dsat_tasks(h)]
    assert sorted(offered) == sorted(ORDER) and len(offered) == len(set(offered))
    assert open_ids(await dsat_tasks(h)) == []


async def test_students_enrolled_before_an_upgrade_get_the_new_sets(h: Harness) -> None:
    # Alex enrolled under 1.0.0 with two open tasks (equiv_001, nonlin_001).
    before = await dsat_tasks(h, ALEX)
    assert open_ids(before) == ["q_dsat_equiv_001", "q_dsat_nonlin_001"]
    await publish_2_0_1(h)
    await replan(h, ALEX)
    assert len(await dsat_tasks(h, ALEX)) == 2  # already two open: nothing added
    await finish(h, next(t for t in before if t["questionId"] == "q_dsat_equiv_001"), ALEX)
    after = await dsat_tasks(h, ALEX)
    new = [t["questionId"] for t in after if t["reason"]["code"] == "NEXT_PRACTICE"]
    assert new == [ORDER[0]]  # the first set in 2.0.1's order he has never had
    assert open_ids(after) == sorted(["q_dsat_nonlin_001", ORDER[0]])


async def test_nothing_is_offered_without_access_or_after_retirement(h: Harness) -> None:
    await enrolled_beth(h)
    starters = await dsat_tasks(h)
    await skip(h, starters[0])  # one open task left: a top-up would normally add one
    grant(h, BETH)  # access revoked
    await replan(h)
    assert len(await dsat_tasks(h)) == 2
    grant(h, BETH, "dsat")
    await post(h, "/api/review/courses/dsat/retire", REVIEWER, {"notes": "test"})
    await replan(h)
    assert len(await dsat_tasks(h)) == 2
    # Calc BC (no practice sequence) is untouched throughout.
    calc = [t for t in (await get(h, "/api/tasks"))["tasks"] if t["courseId"] == "calc_bc"]
    assert all(t["reason"]["code"] != "NEXT_PRACTICE" for t in calc)


async def test_other_students_are_never_affected(h: Harness) -> None:
    await enrolled_beth(h)
    alex_before = await dsat_tasks(h, ALEX)
    await finish(h, (await dsat_tasks(h))[0])
    await replan(h)
    assert await dsat_tasks(h, ALEX) == alex_before


def test_validator_checks_the_practice_sequence() -> None:
    bad = copy.deepcopy(PKG)
    bad["practiceSequence"][0]["questionId"] = "q_does_not_exist"
    bad["practiceSequence"][1]["questionId"] = PKG["starterTasks"][0]["questionId"]
    bad["practiceSequence"][2]["mode"] = "EXAM_CRUNCH"
    issues = {(e.path, e.code) for e in validate_package(bad).report.errors}
    assert issues == {
        ("practiceSequence[0].questionId", "unknown_question"),
        ("practiceSequence[1].questionId", "duplicate"),
        ("practiceSequence[2].mode", "unsupported_mode"),
    }
    assert validate_package(PKG).report.valid
