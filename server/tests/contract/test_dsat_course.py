"""Digital SAT as an independent course on the shared runtime (M3, second-course candidate).

Choice sets are scored by key through the `choice-scoring` ability: no model call, the
answer key never reaches the client, and evidence flows through the same AssessmentService
as Calculus. Nothing in one course changes another course's record.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.support import Harness, ScriptedProvider, build_harness

ALEX, BETH = "stu_alex", "stu_beth"
TASK = "task_alex_dsat_01"  # seeded, pinned to q_dsat_equiv_001 (key: A, C, B)
SKILL = "dsat.advanced-math.equivalent-expressions"


@pytest.fixture
def provider() -> ScriptedProvider:
    return ScriptedProvider()


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch, provider: ScriptedProvider) -> Harness:
    return build_harness(clean_env, llm_provider=provider)


async def get(h: Harness, path: str, sid: str = ALEX, status: int = 200) -> Any:
    r = await h.client.get(path, headers=h.auth(sid))
    assert r.status_code == status, r.text
    return r.json()


def evidence(mastery: dict[str, Any]) -> int:
    """Accepted evidence recorded for the target skill (0 if not listed)."""
    found = [m for m in mastery["mastery"] if m["skillId"] == SKILL]
    return int(found[0]["evidenceCount"]) if found else 0


async def enroll(h: Harness, sid: str = ALEX) -> int:
    r = await h.client.post("/api/courses/enroll", json={"courseId": "dsat"}, headers=h.cmd(sid))
    return r.status_code


async def start(h: Harness) -> dict[str, Any]:
    r = await h.client.post("/api/sessions", json={"taskId": TASK}, headers=h.cmd(ALEX))
    assert r.status_code == 201, r.text
    return dict(r.json())


async def submit(h: Harness, session_id: str, text: str) -> None:
    r = await h.client.post(
        f"/api/sessions/{session_id}/submissions",
        json={"questionId": "q_dsat_equiv_001", "questionVersion": "1",
              "answer": {"text": text, "fileIds": []}},
        headers=h.cmd(ALEX),
    )  # fmt: skip
    assert r.status_code == 202, r.text
    await h.settle()


async def test_dsat_runs_the_same_loop_scored_by_key(
    h: Harness, provider: ScriptedProvider
) -> None:
    assert await enroll(h) == 200
    session = await start(h)
    items = session["activity"]["items"]
    assert [i["itemId"] for i in items] == ["1", "2", "3"]
    assert "answerKey" not in str(session)  # the key never leaves the server

    calc_before = await get(h, "/api/mastery?courseId=calc_bc")
    await submit(h, session["sessionId"], "1: A\n2: B\n3: B")
    assert provider.calls == []  # scored by key, no model

    [a] = (await get(h, f"/api/assessments?sessionId={session['sessionId']}"))["assessments"]
    assert a["status"] == "accepted"
    assert [r["earned"] for r in a["rubricResults"]] == [1, 0, 1]
    assert a["provenance"]["modelVersion"] == "rule:choice-scoring-v1"

    assert evidence(await get(h, "/api/mastery?courseId=dsat")) == 1
    assert await get(h, "/api/mastery?courseId=calc_bc") == calc_before

    # No cross-course effect and, with no consumer registered, no consumer wake.
    events = (await get(h, "/api/events?after=0&limit=100"))["events"]
    assert not any(e["type"].startswith("prerequisite.") for e in events)
    assert not [p for p in h.store.paths(f"students/{ALEX}/outbox/") if "wake." in p]
    assert {t["courseId"] for t in (await get(h, "/api/tasks"))["tasks"]} >= {"dsat", "calc_bc"}


async def test_unreadable_choices_record_no_evidence(h: Harness) -> None:
    await enroll(h)
    session = await start(h)
    await submit(h, session["sessionId"], "I think B, then maybe C?")
    [a] = (await get(h, f"/api/assessments?sessionId={session['sessionId']}"))["assessments"]
    assert a["status"] == "insufficient_evidence" and a["skillEvidence"] == []
    assert evidence(await get(h, "/api/mastery?courseId=dsat")) == 0


async def test_dsat_access_and_isolation(h: Harness) -> None:
    # Beth has no Digital SAT entitlement and cannot see Alex's DSAT task.
    assert await enroll(h, BETH) == 403
    await get(h, f"/api/tasks/{TASK}", sid=BETH, status=404)
    r = await h.client.post("/api/sessions", json={"taskId": TASK}, headers=h.cmd(BETH))
    assert r.status_code == 404


async def test_removed_cross_course_routes_are_gone(h: Harness) -> None:
    await get(h, "/api/prerequisites", status=404)
