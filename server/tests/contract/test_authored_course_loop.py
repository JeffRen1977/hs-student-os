"""Step 27.2: Digital SAT, rebuilt as a course package, runs on the shared runtime.

Starting from a platform with *no* Digital SAT installed, the content file
`content/authored/dsat/package.json` goes through the Step 26 gate over the API (upload →
validator report → submit → reviewer approval → activation). A synthetic student then runs
the loop for both courses side by side — task → session → assessment → mastery → plan —
with no Digital SAT code anywhere in `app/`. Course-internal follow-up rules (Step 24.2)
are not built yet, so this loop stops at the plan.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.registries.content import DEFAULT_CONTENT_ROOT
from tests.support import Harness, ScriptedProvider, build_harness, grade

BETH = "stu_beth"  # enrolled in Calc BC; no Digital SAT access until the platform grants it
AUTHOR, REVIEWER = "author_hsos", "reviewer_platform"
PACKAGE = json.loads((DEFAULT_CONTENT_ROOT / "authored/dsat/package.json").read_text())
CALC_TASK = "task_beth_calc_01"  # q_calc_bc_001 (chain rule)
CALC_ANSWER = (
    "Inner g(x) = x^3 + 1, outer sin u. So h'(x) = cos(x^3 + 1) * 3x^2 = 3x^2 cos(x^3 + 1)"
)
CALC_GRADE = grade(
    CALC_ANSWER,
    {
        "identify-inner-outer": (1, ["Inner g(x) = x^3 + 1, outer sin u"]),
        "apply-chain-rule": (1, ["cos(x^3 + 1) * 3x^2"]),
        "final-answer": (1, ["3x^2 cos(x^3 + 1)"]),
    },
    final="3*x**2*cos(x**3 + 1)",
)


@pytest.fixture
def provider() -> ScriptedProvider:
    return ScriptedProvider()


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch, provider: ScriptedProvider) -> Harness:
    return build_harness(clean_env, llm_provider=provider, seed_packages=False)


async def post(h: Harness, path: str, uid: str, body: dict[str, Any], status: int) -> Any:
    r = await h.client.post(path, json=body, headers=h.cmd(uid))
    assert r.status_code == status, r.text
    return r.json()


async def get(h: Harness, path: str, uid: str = BETH) -> Any:
    r = await h.client.get(path, headers=h.auth(uid))
    assert r.status_code == 200, r.text
    return r.json()


async def run_submission(h: Harness, session: dict[str, Any], text: str) -> dict[str, Any]:
    act = session["activity"]
    body = {"questionId": act["questionId"], "questionVersion": act["questionVersion"],
            "answer": {"text": text, "fileIds": []}}  # fmt: skip
    await post(h, f"/api/sessions/{session['sessionId']}/submissions", BETH, body, 202)
    await h.settle()
    [a] = (await get(h, f"/api/assessments?sessionId={session['sessionId']}"))["assessments"]
    return dict(a)


def evidence(mastery: dict[str, Any]) -> dict[str, int]:
    return {m["skillId"]: m["evidenceCount"] for m in mastery["mastery"] if m["evidenceCount"]}


async def test_digital_sat_goes_through_the_gate_and_runs_beside_calc_bc(
    h: Harness, provider: ScriptedProvider
) -> None:
    catalog = await get(h, "/api/courses/catalog")
    assert "dsat" not in {c["courseId"] for c in catalog["courses"]}

    # --- Authoring and review: data only, through the API ---------------------------------
    draft = await post(h, "/api/authoring/packages", AUTHOR, {"package": PACKAGE}, 201)
    assert draft["report"]["valid"] and draft["report"]["errors"] == []
    assert draft["report"]["evaluation"] == {
        "autoCases": 12, "autoPassed": 12, "modelCases": 0, "failures": []
    }  # fmt: skip
    base = "/api/authoring/packages/dsat/versions/1.0.0"
    review = "/api/review/packages/dsat/versions/1.0.0"
    await post(h, f"{base}/submit", AUTHOR, {}, 200)
    approval = {
        "notes": "Evaluation set passes; original synthetic content.",
        "licenseAttested": True,
    }
    await post(h, f"{review}/approve", REVIEWER, approval, 200)
    await post(h, f"{review}/activate", REVIEWER, {}, 200)

    # --- Platform-managed access, then enrollment with the package's starter tasks --------
    h.put_doc(
        f"students/{BETH}/access/current",
        {"apCourses": ["calc_bc"], "courses": ["dsat"], "admissions": False,
         "updatedAt": h.clock.now(), "updatedBy": "admin-test"},
    )  # fmt: skip
    await post(h, "/api/courses/enroll", BETH, {"courseId": "dsat"}, 200)
    agent = await get(h, "/api/courses/dsat/agent")
    assert {s["skillId"] for s in agent["skills"]} >= {"dsat.advanced-math.equivalent-expressions"}
    tasks = (await get(h, "/api/tasks"))["tasks"]
    dsat_tasks = sorted(
        (t for t in tasks if t["courseId"] == "dsat"), key=lambda t: t["questionId"]
    )
    assert [t["questionId"] for t in dsat_tasks] == ["q_dsat_equiv_001", "q_dsat_nonlin_001"]
    assert {t["courseId"] for t in tasks} == {"calc_bc", "dsat"}

    # --- Digital SAT: key-scored choice set, no model call ---------------------------------
    sat = await post(h, "/api/sessions", BETH, {"taskId": dsat_tasks[0]["taskId"]}, 201)
    assert sat["contextVersion"] == {"pack": "1.0.0", "workflow": "dsat-practice-v1"}
    assert "answerKey" not in json.dumps(sat)
    a_sat = await run_submission(h, sat, "1: A\n2: C\n3: B")
    assert a_sat["status"] == "accepted" and provider.calls == []
    assert a_sat["provenance"]["modelVersion"] == "rule:choice-scoring-v1"
    done = await post(h, f"/api/sessions/{sat['sessionId']}/complete", BETH, {}, 200)
    assert done["status"] == "COMPLETED"

    # --- Calc BC on the same runtime: model-graded rubric ----------------------------------
    provider.queue(CALC_GRADE)
    calc = await post(h, "/api/sessions", BETH, {"taskId": CALC_TASK}, 201)
    a_calc = await run_submission(h, calc, CALC_ANSWER)
    assert a_calc["status"] == "accepted" and len(provider.calls) == 1

    # --- Mastery stays inside each course ---------------------------------------------------
    sat_m = evidence(await get(h, "/api/mastery?courseId=dsat"))
    calc_m = evidence(await get(h, "/api/mastery?courseId=calc_bc"))
    assert sat_m == {"dsat.advanced-math.equivalent-expressions": 1}
    assert calc_m and all(k.startswith("calc_bc.") for k in calc_m)

    # --- One plan across both enrolled courses ----------------------------------------------
    await post(h, "/api/plans/replan", BETH, {}, 202)
    await h.settle()
    plan = await get(h, "/api/plans/latest")
    by_id = {t["taskId"]: t for t in (await get(h, "/api/tasks"))["tasks"]}
    planned_courses = {by_id[e["taskId"]]["courseId"] for e in plan["entries"]}
    assert planned_courses == {"calc_bc", "dsat"}
    assert all(e["explanation"] for e in plan["entries"])
