"""Step 34.2–34.3: APUSH onboarded as an authored package, with the new platform ability
`source-analysis` (document-based writing graded against the question's sources).

- The seeded package waits in the review queue; it reaches students only after a
  platform reviewer approves it, attesting the model-graded evaluation cases, and
  activates it.
- A document-based session shows its source documents; the grader sees them fenced as
  untrusted content, and a grade that cites any other document is rejected.
- Nothing in the runtime is APUSH-specific: the same ability works for any course.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.support import Harness, ScriptedProvider, build_harness

ALEX = "stu_alex"
AUTHOR, REVIEWER = "author_hsos", "reviewer_platform"
REVIEW = "/api/review/packages/apush/versions/1.0.0"
PUBLICATION = REVIEW.replace("/api/review/", "/api/admin/")
DOC_A, DOC_B = "mat_apush_doc_a_federalist10", "mat_apush_doc_b_brutus1"
ESSAY = (
    "The debate centered on the size of the republic to a large extent. "
    "Under the Articles of Confederation the national government was weak. "
    "Madison argues that many factions in a large republic stop one majority from uniting. "
    "Brutus warns that people with different interests would make representatives fight. "
    "Madison wrote to persuade New York voters, so he presents size as a strength."
)


@pytest.fixture
def provider() -> ScriptedProvider:
    return ScriptedProvider()


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch, provider: ScriptedProvider) -> Harness:
    return build_harness(clean_env, llm_provider=provider)


async def post(h: Harness, path: str, uid: str, body: dict[str, Any], status: int) -> Any:
    r = await h.client.post(path, json=body, headers=h.cmd(uid))
    assert r.status_code == status, r.text
    return r.json()


async def get(h: Harness, path: str, uid: str = ALEX, status: int = 200) -> Any:
    r = await h.client.get(path, headers=h.auth(uid))
    assert r.status_code == status, r.text
    return r.json()


def grant_apush(h: Harness) -> None:
    h.put_doc(
        f"students/{ALEX}/access/current",
        {"apCourses": ["calc_bc", "apush"], "courses": ["dsat"], "admissions": False,
         "updatedAt": h.clock.now(), "updatedBy": "admin-test"},
    )  # fmt: skip


async def activate_apush(h: Harness) -> None:
    await post(
        h, f"{REVIEW}/approve", REVIEWER,
        {"notes": "Ran the model-graded cases.", "licenseAttested": True,
         "modelEvaluationAttested": True}, 200,
    )  # fmt: skip
    await post(h, f"{PUBLICATION}/activate", "admin_platform", {}, 200)


async def dbq_session(h: Harness) -> dict[str, Any]:
    await activate_apush(h)
    grant_apush(h)
    await post(h, "/api/courses/enroll", ALEX, {"courseId": "apush"}, 200)
    tasks = [t for t in (await get(h, "/api/tasks"))["tasks"] if t["courseId"] == "apush"]
    assert {t["questionId"] for t in tasks} == {
        "q_apush_saq_001", "q_apush_mc_001", "q_apush_dbq_001",
    }  # fmt: skip
    dbq = next(t for t in tasks if t["questionId"] == "q_apush_dbq_001")
    return dict(await post(h, "/api/sessions", ALEX, {"taskId": dbq["taskId"]}, 201))


def source_grade(cited: dict[str, list[str]]) -> dict[str, Any]:
    quotes = {
        "thesis": "The debate centered on the size of the republic to a large extent.",
        "doc-a": "many factions in a large republic stop one majority from uniting",
        "doc-b": "people with different interests would make representatives fight",
        "context": "Under the Articles of Confederation the national government was weak.",
        "sourcing": "Madison wrote to persuade New York voters",
    }
    return {
        "status": "accepted",
        "statusReasons": [],
        "criteria": [
            {
                "criterionId": cid,
                "earned": 1,
                "assessable": True,
                "evidenceQuotes": [q],
                "documentsCited": cited.get(cid, []),
            }
            for cid, q in quotes.items()
        ],
        "finalExpression": "",
        "uncertainty": "low",
        "uncertaintyReasons": [],
        "feedback": "Your claim is clear. Explain Brutus's audience as well.",
    }


async def submit(h: Harness, session: dict[str, Any]) -> str:
    act = session["activity"]
    body = {"questionId": act["questionId"], "questionVersion": act["questionVersion"],
            "answer": {"text": ESSAY}}  # fmt: skip
    r = await post(h, f"/api/sessions/{session['sessionId']}/submissions", ALEX, body, 202)
    return str(r["runId"])


async def test_apush_waits_for_review_and_needs_model_evaluation_attested(h: Harness) -> None:
    queue = await get(h, "/api/review/packages", REVIEWER)
    apush = next(v for v in queue["versions"] if v["courseId"] == "apush")
    assert apush["status"] == "submitted" and apush["review"] is None
    assert apush["report"]["evaluation"] == {
        "autoCases": 3, "autoPassed": 3, "modelCases": 4, "failures": [],
    }  # fmt: skip
    catalog = {c["courseId"] for c in (await get(h, "/api/courses/catalog"))["courses"]}
    assert "apush" not in catalog

    # Model-graded cases exist, so approval needs the reviewer's attestation.
    r = await h.client.post(
        f"{REVIEW}/approve",
        json={"notes": "", "licenseAttested": True},
        headers=h.cmd(REVIEWER),
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "REVIEW_REQUIREMENTS_NOT_MET"
    await activate_apush(h)
    catalog = {c["courseId"]: c for c in (await get(h, "/api/courses/catalog"))["courses"]}
    assert catalog["apush"]["status"] == "available"  # admin published for all students
    assert catalog["apush"]["agent"]["supportedTaskTypes"] == ["FRQ_PRACTICE", "PRACTICE"]


async def test_document_based_session_shows_its_sources(h: Harness) -> None:
    session = await dbq_session(h)
    sources = session["activity"]["sources"]
    assert [s["materialId"] for s in sources] == [DOC_A, DOC_B]
    assert sources[0]["text"].startswith("Extend the sphere")
    assert "public domain" in sources[0]["sourceRef"].lower()


async def test_source_analysis_grades_with_fenced_sources(
    h: Harness, provider: ScriptedProvider
) -> None:
    session = await dbq_session(h)
    provider.queue(source_grade({"doc-a": [DOC_A], "doc-b": [DOC_B], "sourcing": [DOC_A]}))
    run_id = await submit(h, session)
    await h.drain()
    run = await get(h, f"/api/runs/{run_id}")
    assert run["status"] == "SUCCEEDED", run
    system = provider.calls[0]["system"]
    assert "Skill: Source-based writing assessment" in system
    assert f'<source_document sourceId="{DOC_A}"' in system and "Extend the sphere" in system
    schema = provider.calls[0]["output_schema"]
    cited = schema["properties"]["criteria"]["items"]["properties"]["documentsCited"]
    assert cited["items"]["enum"] == [DOC_A, DOC_B]
    assessment = (await get(h, f"/api/assessments?sessionId={session['sessionId']}"))[
        "assessments"
    ][0]
    assert assessment["status"] == "accepted"
    assert sum(c["earned"] for c in assessment["rubricResults"]) == 5
    # Evidence is always a span of the student's own essay.
    for c in assessment["rubricResults"]:
        assert all(":text:" in ref for ref in c["evidenceRefs"])


async def test_citing_a_document_outside_the_question_is_rejected(
    h: Harness, provider: ScriptedProvider
) -> None:
    session = await dbq_session(h)
    bad = source_grade({"doc-a": ["mat_not_a_source"]})
    provider.queue(bad, bad, bad)  # every attempt cites an unknown document
    run_id = await submit(h, session)
    await h.drain()
    run = await get(h, f"/api/runs/{run_id}")
    assert run["status"] == "FAILED"
    assert run["error"]["code"] == "MODEL_OUTPUT_INVALID"
    assert (await get(h, f"/api/assessments?sessionId={session['sessionId']}"))["assessments"] == []
