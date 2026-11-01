"""Step 18: the Calculus learning loop through the API and worker, with a scripted model.

Hint → submission → atomic assessment commit (assessment + mastery + run + events) →
complete. Plus the failure windows: crash at commit, stale lease, concurrent cancel,
replayed commit, budget exhaustion, invalid model output, semantically invalid drafts.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from app.adapters.firestore.memory_store import SimulatedCommitFailure
from app.domain.ports.execution import ExecutionOutput, ExecutionRequest, RunExecutor
from app.domain.run_execution import LeaseGrant
from tests.support import Harness, ScriptedProvider, build_harness, grade, idem

SID = "stu_alex"
TASK = "task_alex_calc_01"  # pinned to q_calc_bc_001 (chain rule)
ANSWER_TEXT = (
    "Inner g(x) = x^3 + 1, outer sin u. So h'(x) = cos(x^3 + 1) * 3x^2 = 3x^2 cos(x^3 + 1)"
)
FULL = {
    "identify-inner-outer": (1, ["Inner g(x) = x^3 + 1, outer sin u"]),
    "apply-chain-rule": (1, ["cos(x^3 + 1) * 3x^2"]),
    "final-answer": (1, ["3x^2 cos(x^3 + 1)"]),
}
CORRECT = grade(ANSWER_TEXT, FULL, final="3*x**2*cos(x**3 + 1)")
SUBMISSION = {
    "questionId": "q_calc_bc_001",
    "questionVersion": "1",
    "answer": {"text": ANSWER_TEXT, "fileIds": []},
}


@pytest.fixture
def provider() -> ScriptedProvider:
    return ScriptedProvider()


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch, provider: ScriptedProvider) -> Harness:
    return build_harness(clean_env, llm_provider=provider)


async def start(h: Harness, sid: str = SID, task: str = TASK) -> dict[str, Any]:
    r = await h.client.post("/api/sessions", json={"taskId": task}, headers=h.cmd(sid))
    assert r.status_code == 201, r.text
    return dict(r.json())


async def submit(h: Harness, session_id: str, body: dict[str, Any] | None = None) -> str:
    r = await h.client.post(
        f"/api/sessions/{session_id}/submissions", json=body or SUBMISSION, headers=h.cmd(SID)
    )
    assert r.status_code == 202, r.text
    return str(r.json()["runId"])


async def get(h: Harness, path: str, sid: str = SID) -> dict[str, Any]:
    r = await h.client.get(path, headers=h.auth(sid))
    assert r.status_code == 200, r.text
    return dict(r.json())


def docs(h: Harness, collection: str, sid: str = SID) -> list[dict[str, Any]]:
    return [h.store.raw(p) for p in h.store.paths(f"students/{sid}/{collection}/")]


def event_types(h: Harness) -> list[str]:
    return [e["type"] for e in sorted(docs(h, "events"), key=lambda e: e["sequence"])]


async def test_full_calculus_loop(h: Harness, provider: ScriptedProvider) -> None:
    session = await start(h)
    assert session["activity"]["questionId"] == "q_calc_bc_001"
    assert "sin(x³ + 1)" in session["activity"]["prompt"] and session["hintCount"] == 0
    sid = session["sessionId"]

    # A hint first: recorded on the session as a server-issued hint.
    provider.queue({"reply": "Which function is applied last?"})
    r = await h.client.post(
        f"/api/sessions/{sid}/messages", json={"text": "Where do I start?"}, headers=h.cmd(SID)
    )
    assert r.status_code == 202
    assert await h.drain() == 1
    messages = (await get(h, f"/api/sessions/{sid}/messages"))["messages"]
    assert [(m["role"], m["synthetic"]) for m in messages] == [
        ("student", False),
        ("agent", False),
    ]
    assert (await get(h, f"/api/sessions/{sid}"))["hintCount"] == 1

    provider.queue(CORRECT)
    run_id = await submit(h, sid)
    assert await h.drain() == 1
    run = await get(h, f"/api/runs/{run_id}")
    assert run["status"] == "SUCCEEDED"
    assessment_id = run["result"]["assessmentId"]
    assert assessment_id and run["result"]["messageId"]

    a = await get(h, f"/api/assessments/{assessment_id}")
    assert a["status"] == "accepted" and a["rubricVersion"] == "1" and a["questionVersion"] == "1"
    assert a["hintUsage"] == {"serverHintCount": 1, "selfReportedHelp": False}
    assert {(e["skillId"], e["observation"]) for e in a["skillEvidence"]} == {
        ("calc_bc.function-composition", "correct_with_hint"),
        ("calc_bc.chain-rule", "correct_with_hint"),  # assisted: never independent
    }
    assert a["uncertainty"]["level"] in ("limited", "high")
    assert a["provenance"]["modelVersion"] == ScriptedProvider.MODEL_VERSION
    assert a["provenance"]["workflowVersion"] == "calc-practice-v1"
    [tool] = docs(h, "toolResults")
    assert a["provenance"]["toolResultIds"] == [tool["toolResultId"]]
    assert tool["status"] == "ok" and tool["output"] == {"equivalent": True}
    sub_id = a["submissionId"]
    for result in a["rubricResults"]:
        assert all(ref.startswith(f"{sub_id}:text:") for ref in result["evidenceRefs"])

    mastery = (await get(h, "/api/mastery?courseId=calc_bc"))["mastery"]
    by_skill = {m["skillId"]: m for m in mastery}
    assert len(by_skill) == 9  # every course skill, evidence or not
    assert by_skill["calc_bc.chain-rule"]["level"] == "emerging"  # assisted only
    assert by_skill["calc_bc.chain-rule"]["independentEvidenceCount"] == 0
    assert by_skill["calc_bc.lhopital"]["level"] == "insufficient_evidence"
    page = await get(h, "/api/mastery?courseId=calc_bc&limit=4")
    assert len(page["mastery"]) == 4 and page["nextCursor"]

    twin = await get(h, "/api/twin")
    assert twin["predictionSummary"]["calc_bc"]["status"] == "unavailable"
    assert twin["masterySummary"]["calc_bc.chain-rule"]["level"] == "emerging"

    types = event_types(h)
    assert types.index("assessment.completed") < types.index("mastery.updated")
    assert types.index("mastery.updated") < len(types) - 1  # run.completed comes last
    assert types[-1] == "run.completed"

    # Complete: Session + Task close; mastery is summarized, not re-applied.
    before = docs(h, "mastery")
    key = idem()
    r = await h.client.post(f"/api/sessions/{sid}/complete", json={}, headers=h.cmd(SID, key))
    assert r.status_code == 200 and r.json()["status"] == "COMPLETED"
    task = await get(h, f"/api/tasks/{TASK}")
    assert task["status"] == "COMPLETED"
    again = await h.client.post(f"/api/sessions/{sid}/complete", json={}, headers=h.cmd(SID, key))
    assert again.status_code == 200 and again.headers["Idempotency-Replayed"] == "true"
    other = await h.client.post(f"/api/sessions/{sid}/complete", json={}, headers=h.cmd(SID))
    assert other.status_code == 200 and other.json()["status"] == "COMPLETED"
    assert docs(h, "mastery") == before
    assert event_types(h).count("session.completed") == 1


async def test_complete_requires_accepted_assessment_and_idle_session(
    h: Harness, provider: ScriptedProvider
) -> None:
    sid = (await start(h))["sessionId"]
    r = await h.client.post(f"/api/sessions/{sid}/complete", json={}, headers=h.cmd(SID))
    assert r.status_code == 409 and r.json()["error"]["code"] == "COMPLETION_REQUIREMENTS_NOT_MET"

    await submit(h, sid)  # queued, not yet graded
    r = await h.client.post(f"/api/sessions/{sid}/complete", json={}, headers=h.cmd(SID))
    assert r.status_code == 409 and r.json()["error"]["code"] == "RUN_IN_PROGRESS"
    r = await h.client.post(f"/api/sessions/{sid}/complete", json={})
    assert r.status_code == 401


async def test_insufficient_evidence_never_updates_mastery(
    h: Harness, provider: ScriptedProvider
) -> None:
    sid = (await start(h))["sessionId"]
    text = "3x^2 cos(x^3 + 1)"
    provider.queue(
        grade(
            text,
            {
                "identify-inner-outer": (0, []),
                "apply-chain-rule": (0, []),
                "final-answer": (1, [text]),
            },
            status="insufficient_evidence",
            final="3*x**2*cos(x**3 + 1)",
            feedback="Show how you got there. " * 60,
        )
    )
    await submit(h, sid, {**SUBMISSION, "answer": {"text": text, "fileIds": []}})
    await h.drain()
    [a] = (await get(h, f"/api/assessments?sessionId={sid}"))["assessments"]
    assert a["status"] == "insufficient_evidence" and a["skillEvidence"] == []
    assert len(a["feedback"]) <= 600  # limited feedback only
    assert docs(h, "mastery") == []
    assert "mastery.updated" not in event_types(h)
    session = await get(h, f"/api/sessions/{sid}")
    assert session["completion"] == {"eligible": False, "reason": "accepted_assessment_required"}
    run = docs(h, "runs")[0]
    assert run["status"] == "SUCCEEDED"  # execution succeeded; the student did not "pass"


class CrashAtCommit:
    """Executes normally, then makes the very next transaction (the commit) fail."""

    def __init__(self, inner: RunExecutor, h: Harness) -> None:
        self.inner, self.h = inner, h

    async def execute(self, request: ExecutionRequest) -> ExecutionOutput:
        output = await self.inner.execute(request)
        self.h.store.fail_next_commits = 1
        return output


async def test_crash_at_commit_leaves_no_partial_state(
    h: Harness, provider: ScriptedProvider
) -> None:
    worker = h.services.run_execution
    real = worker._executor
    worker._executor = CrashAtCommit(real, h)
    sid = (await start(h))["sessionId"]
    provider.queue(CORRECT)
    run_id = await submit(h, sid)
    with pytest.raises(SimulatedCommitFailure):
        await h.drain()
    assert docs(h, "assessments") == [] and docs(h, "mastery") == []
    assert "assessment.completed" not in event_types(h)
    assert h.store.raw(f"students/{SID}/runs/{run_id}")["status"] == "RUNNING"

    # The lease expires, recovery re-queues, a healthy worker finishes exactly once.
    worker._executor = real
    provider.queue(CORRECT)
    h.clock.advance(seconds=h.services.settings.run_lease_seconds + 1)
    assert await h.services.recovery.requeue_stalled() == 1
    await h.drain()
    assert len(docs(h, "assessments")) == 1
    [m] = [m for m in docs(h, "mastery") if m["skillId"] == "calc_bc.chain-rule"]
    assert m["evidenceCount"] == 1


async def test_stale_lease_and_replayed_commit(h: Harness, provider: ScriptedProvider) -> None:
    sid = (await start(h))["sessionId"]
    run_id = await submit(h, sid)
    worker = h.services.run_execution
    actor = worker.actor_for(SID)
    old = await worker.acquire(actor, run_id)
    assert isinstance(old, LeaseGrant)
    provider.queue(CORRECT, CORRECT)
    old_output = await worker._executor.execute(old.request)

    h.clock.advance(seconds=h.services.settings.run_lease_seconds + 1)
    new = await worker.acquire(actor, run_id)  # a second worker takes over
    assert isinstance(new, LeaseGrant) and new.token == old.token + 1
    assert await worker.commit(actor, run_id, old.token, old_output) is False  # fenced out
    assert docs(h, "assessments") == []

    new_output = await worker._executor.execute(new.request)
    assert await worker.commit(actor, run_id, new.token, new_output) is True
    assert await worker.commit(actor, run_id, new.token, new_output) is False  # replay
    assert len(docs(h, "assessments")) == 1
    assert event_types(h).count("assessment.completed") == 1


async def test_cancellation_during_grading_discards_the_result(
    h: Harness, provider: ScriptedProvider
) -> None:
    sid = (await start(h))["sessionId"]
    run_id = await submit(h, sid)
    worker = h.services.run_execution
    actor = worker.actor_for(SID)
    grant = await worker.acquire(actor, run_id)
    assert isinstance(grant, LeaseGrant)
    r = await h.client.post(f"/api/runs/{run_id}/cancel", json={}, headers=h.cmd(SID))
    assert r.status_code == 202
    provider.queue(CORRECT)
    output = await worker._executor.execute(grant.request)
    assert await worker.commit(actor, run_id, grant.token, output) is True
    run = await get(h, f"/api/runs/{run_id}")
    assert run["status"] == "CANCELLED" and run["result"] is None
    assert docs(h, "assessments") == [] and docs(h, "mastery") == []
    assert (await get(h, f"/api/sessions/{sid}"))["activeRunId"] is None


async def test_assessments_are_isolated_per_student(h: Harness, provider: ScriptedProvider) -> None:
    sid = (await start(h))["sessionId"]
    provider.queue(CORRECT)
    run_id = await submit(h, sid)
    await h.drain()
    assessment_id = (await get(h, f"/api/runs/{run_id}"))["result"]["assessmentId"]
    for path in (f"/api/assessments/{assessment_id}", f"/api/assessments?sessionId={sid}"):
        r = await h.client.get(path, headers=h.auth("stu_beth"))
        assert r.status_code == 404, path
    beth = await get(h, "/api/mastery?courseId=calc_bc", sid="stu_beth")
    assert {m["level"] for m in beth["mastery"]} == {"insufficient_evidence"}
    r = await h.client.get("/api/mastery?courseId=nope_course", headers=h.auth(SID))
    assert r.status_code == 404


async def test_invalid_model_output_fails_the_run_without_evidence(
    h: Harness, provider: ScriptedProvider
) -> None:
    sid = (await start(h))["sessionId"]
    provider.queue("{not json", {"status": "accepted"}, {"criteria": "nope"})
    run_id = await submit(h, sid)
    await h.drain()
    run = await get(h, f"/api/runs/{run_id}")
    assert run["status"] == "FAILED"
    assert run["error"] == {"code": "MODEL_OUTPUT_INVALID", "retryable": False}
    assert docs(h, "assessments") == []


class TamperedDraft:
    """A buggy skill that cites evidence outside the stored answer."""

    def __init__(self, inner: RunExecutor) -> None:
        self.inner = inner

    async def execute(self, request: ExecutionRequest) -> ExecutionOutput:
        output = await self.inner.execute(request)
        assert output.assessment is not None
        sub = output.assessment.submission_id
        bad = [dataclasses.replace(r, evidence_refs=(f"{sub}:text:0-99999",))
               if r.earned else r for r in output.assessment.rubric_results]  # fmt: skip
        return dataclasses.replace(
            output, assessment=dataclasses.replace(output.assessment, rubric_results=bad)
        )


async def test_semantically_invalid_draft_is_rejected_atomically(
    h: Harness, provider: ScriptedProvider
) -> None:
    worker = h.services.run_execution
    worker._executor = TamperedDraft(worker._executor)
    sid = (await start(h))["sessionId"]
    provider.queue(CORRECT)
    run_id = await submit(h, sid)
    await h.drain()
    run = await get(h, f"/api/runs/{run_id}")
    assert run["status"] == "FAILED" and run["error"]["code"] == "ASSESSMENT_REJECTED"
    assert docs(h, "assessments") == [] and docs(h, "mastery") == []
    assert docs(h, "toolResults") == [] and "assessment.completed" not in event_types(h)


async def test_budget_exhaustion_fails_the_run_and_blocks_new_commands(
    clean_env: pytest.MonkeyPatch,
) -> None:
    provider = ScriptedProvider(CORRECT)
    h = build_harness(clean_env, llm_provider=provider, llm_run_token_budget=1_000)
    sid = (await start(h))["sessionId"]
    run_id = await submit(h, sid)
    await h.drain()
    run = await get(h, f"/api/runs/{run_id}")
    assert run["error"] == {"code": "BUDGET_EXCEEDED", "retryable": False}
    assert provider.calls == []  # refused before contacting the model

    day = f"day-{h.clock.now().date().isoformat()}"
    h.put_doc(
        f"students/{SID}/usage/{day}",
        {"key": day, "scope": "day", "usedTokens": 10_000_000, "reservations": {}},
    )
    r = await h.client.post(
        f"/api/sessions/{sid}/messages", json={"text": "hi"}, headers=h.cmd(SID)
    )
    assert r.status_code == 429 and r.json()["error"]["code"] == "BUDGET_EXCEEDED"


async def test_correction_after_feedback_is_not_independent(
    h: Harness, provider: ScriptedProvider
) -> None:
    sid = (await start(h))["sessionId"]
    wrong_text = "outer sin, inner x^3 + 1, so h'(x) = cos(x^3 + 1)"
    provider.queue(
        grade(
            wrong_text,
            {
                "identify-inner-outer": (1, ["outer sin, inner x^3 + 1"]),
                "apply-chain-rule": (0, []),
                "final-answer": (0, []),
            },
            final="cos(x**3 + 1)",
        ),
        CORRECT,
    )
    await submit(h, sid, {**SUBMISSION, "answer": {"text": wrong_text, "fileIds": []}})
    await h.drain()
    await submit(h, sid)  # the corrected attempt, after seeing feedback
    await h.drain()
    first, second = (await get(h, f"/api/assessments?sessionId={sid}"))["assessments"]
    assert ("calc_bc.chain-rule", "incorrect") in {
        (e["skillId"], e["observation"]) for e in first["skillEvidence"]
    }
    assert {e["observation"] for e in second["skillEvidence"]} == {"correct_with_hint"}
    assert "correction_after_feedback" in second["uncertainty"]["reasons"]


async def test_an_assessment_can_be_regraded_only_once(
    h: Harness, provider: ScriptedProvider
) -> None:
    """Two regrades of the same assessment would both count; the second is rejected."""
    from app.adapters.firestore.assessment_repository import assessment_to_doc
    from app.domain.assessment_service import AssessmentRejectedError
    from app.domain.ports.repositories import Tx
    from app.domain.run_execution import WORKER_SERVICE
    from app.domain.types.actor import ActorContext
    from app.domain.types.assessment_draft import AssessmentDraft

    sid = (await start(h))["sessionId"]
    provider.queue(CORRECT)
    run_id = await submit(h, sid)
    assert await h.drain() == 1
    first = await get(h, f"/api/runs/{run_id}")
    original_id = first["result"]["assessmentId"]
    actor = ActorContext.for_service(WORKER_SERVICE, SID)

    async def load(tx: Tx) -> Any:
        run = await tx.runs.get(actor, run_id)
        return run, await tx.assessments.get(actor, original_id)

    run, original = await h.services.uow.transaction(load)
    # An earlier regrade already replaced the original.
    h.put_doc(
        f"students/{SID}/assessments/asm_run_regrade_1",
        assessment_to_doc(
            dataclasses.replace(
                original,
                assessment_id="asm_run_regrade_1",
                run_id="run_regrade_1",
                supersedes_assessment_id=original_id,
            )
        ),
    )
    draft = AssessmentDraft(
        submission_id=original.submission_id,
        question_id=original.question_id,
        question_version=original.question_version,
        rubric_id=original.rubric_id,
        rubric_version=original.rubric_version,
        status=original.status,
        rubric_results=original.rubric_results,
        uncertainty=original.uncertainty,
        feedback="regrade",
        model_version=original.provenance.model_version,
        workflow_version=original.provenance.workflow_version,
        supersedes_assessment_id=original_id,
    )

    async def regrade(tx: Tx) -> None:
        await h.services.assessments.commit_assessment(
            tx, actor, dataclasses.replace(run, run_id="run_regrade_2"), draft,
            tool_result_ids=set(), now=h.clock.now(),
        )  # fmt: skip

    with pytest.raises(AssessmentRejectedError, match="already_replaced"):
        await h.services.uow.transaction(regrade)
