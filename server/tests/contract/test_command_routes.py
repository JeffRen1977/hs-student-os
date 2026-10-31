"""Step 14: commands create Submission/Message + Run + idempotency + outbox atomically."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from httpx import Response

from app.domain.types.run import InputRequestKind
from tests.support import Harness, idem

ANSWER = {
    "questionId": "q_calc_bc_001",
    "questionVersion": "1",
    "answer": {"text": "h'(x) = 3x^2 cos(x^3 + 1)", "fileIds": []},
}


async def _session(h: Harness, sid: str = "stu_alex", task: str = "task_alex_calc_01") -> str:
    response = await h.client.post("/api/sessions", json={"taskId": task}, headers=h.cmd(sid))
    assert response.status_code in (200, 201), response.text
    return str(response.json()["sessionId"])


async def _submit(
    h: Harness, session_id: str, body: dict[str, Any] | None = None, key: str | None = None,
    sid: str = "stu_alex",
) -> Response:  # fmt: skip
    return await h.client.post(
        f"/api/sessions/{session_id}/submissions", json=body or ANSWER, headers=h.cmd(sid, key)
    )


def _docs(h: Harness, collection: str, sid: str = "stu_alex") -> list[dict[str, Any]]:
    return [h.store.raw(p) for p in h.store.paths(f"students/{sid}/{collection}/")]


async def test_submission_is_accepted_atomically(harness: Harness) -> None:
    session_id = await _session(harness)
    harness.queue.enqueue = _noop  # type: ignore[method-assign]  # inspect pre-dispatch state
    response = await _submit(harness, session_id)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "QUEUED"
    [submission] = _docs(harness, "submissions")
    [run] = _docs(harness, "runs")
    [outbox] = _docs(harness, "outbox")
    assert (
        submission["submissionId"] == body["submissionId"] and submission["runId"] == run["runId"]
    )
    assert run["kind"] == "ASSESS_SUBMISSION" and run["status"] == "QUEUED"
    assert outbox["runId"] == run["runId"] and outbox["deliveryId"] == f"{run['runId']}.g1"
    assert len(_docs(harness, "idempotency")) == 2  # session start + submission
    assert "answer" not in str(_docs(harness, "idempotency"))  # no student content stored
    session = harness.store.raw(f"students/stu_alex/sessions/{session_id}")
    assert session["activeRunId"] == run["runId"]
    types = [e["type"] for e in sorted(_docs(harness, "events"), key=lambda e: e["sequence"])]
    assert types == ["session.started", "run.queued"]
    get_run = await harness.client.get(
        f"/api/runs/{run['runId']}", headers=harness.auth("stu_alex")
    )
    assert get_run.status_code == 200
    assert get_run.json()["submissionId"] == body["submissionId"]
    assert "leaseFencingToken" not in get_run.json() and "cancelRequested" not in get_run.json()


async def _noop(*_args: object) -> None:
    return None


async def test_duplicate_submission_returns_same_result(harness: Harness) -> None:
    session_id = await _session(harness)
    key = idem()
    first = await _submit(harness, session_id, key=key)
    replay = await _submit(harness, session_id, key=key)
    assert replay.status_code == 202
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["submissionId"] == first.json()["submissionId"]
    assert replay.json()["runId"] == first.json()["runId"]
    assert len(_docs(harness, "submissions")) == 1 and len(_docs(harness, "runs")) == 1


async def test_same_key_different_body_is_409(harness: Harness) -> None:
    session_id = await _session(harness)
    key = idem()
    await _submit(harness, session_id, key=key)
    changed = {**ANSWER, "answer": {"text": "a different answer", "fileIds": []}}
    response = await _submit(harness, session_id, changed, key=key)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert "different answer" not in response.text


async def test_concurrent_commands_allow_one_active_run(harness: Harness) -> None:
    session_id = await _session(harness)
    responses = await asyncio.gather(*(_submit(harness, session_id) for _ in range(4)))
    codes = sorted(r.status_code for r in responses)
    assert codes == [202, 409, 409, 409]
    assert {r.json()["error"]["code"] for r in responses if r.status_code == 409} == {
        "RUN_IN_PROGRESS"
    }
    message = await harness.client.post(
        f"/api/sessions/{session_id}/messages",
        json={"text": "hint?"},
        headers=harness.cmd("stu_alex"),
    )
    assert message.status_code == 409
    assert len(_docs(harness, "runs")) == 1


async def test_after_run_finishes_a_new_command_is_accepted(harness: Harness) -> None:
    session_id = await _session(harness)
    first = await _submit(harness, session_id)
    await harness.drain()
    run = await harness.client.get(
        f"/api/runs/{first.json()['runId']}", headers=harness.auth("stu_alex")
    )
    assert run.json()["status"] == "SUCCEEDED"
    correction = {**ANSWER, "supersedesSubmissionId": first.json()["submissionId"]}
    second = await _submit(harness, session_id, correction)
    assert second.status_code == 202
    subs = await harness.client.get(
        f"/api/sessions/{session_id}/submissions", headers=harness.auth("stu_alex")
    )
    assert [s["supersedesSubmissionId"] for s in subs.json()["submissions"]] == [
        None,
        first.json()["submissionId"],
    ]


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ({"questionId": "q_dsat_001"}, 404),  # not in this session's course
        ({"questionVersion": "2"}, 400),
        ({"supersedesSubmissionId": "sub_unknown"}, 404),
        ({"answer": {"text": "x", "fileIds": ["file_beth"]}}, 404),  # another student's file
        ({"answer": {"text": "x", "fileIds": ["file_pending"]}}, 409),
        ({"scoreDelta": 1}, 400),
        ({"assessmentStatus": "accepted"}, 400),
    ],
)
async def test_invalid_references_are_rejected(
    harness: Harness, change: dict[str, Any], status: int
) -> None:
    harness.put_doc("students/stu_beth/files/file_beth", {"status": "ready"})
    harness.put_doc("students/stu_alex/files/file_pending", {"status": "pending"})
    session_id = await _session(harness)
    response = await _submit(harness, session_id, {**ANSWER, **change})
    assert response.status_code == status, response.text
    assert _docs(harness, "runs") == [] and _docs(harness, "submissions") == []


async def test_own_ready_file_is_accepted(harness: Harness) -> None:
    harness.put_doc("students/stu_alex/files/file_ok", {"status": "ready"})
    session_id = await _session(harness)
    body = {**ANSWER, "answer": {"text": "see photo", "fileIds": ["file_ok"]}}
    assert (await _submit(harness, session_id, body)).status_code == 202


async def test_commands_on_foreign_or_closed_sessions(harness: Harness) -> None:
    beth_session = await _session(harness, "stu_beth", "task_beth_calc_01")
    assert (await _submit(harness, beth_session)).status_code == 404
    alex_session = await _session(harness)
    await harness.client.post(
        f"/api/sessions/{alex_session}/abandon", json={}, headers=harness.cmd("stu_alex")
    )
    closed = await _submit(harness, alex_session)
    assert closed.status_code == 409
    assert closed.json()["error"]["code"] == "INVALID_STATE_TRANSITION"


async def test_lost_entitlement_blocks_commands(harness: Harness) -> None:
    session_id = await _session(harness)
    harness.put_doc(
        "students/stu_alex/access/current", {"apCourses": [], "dsat": True, "admissions": False}
    )
    response = await _submit(harness, session_id)
    assert response.status_code == 403


async def test_transaction_failure_leaves_no_partial_state(harness: Harness) -> None:
    session_id = await _session(harness)
    before = harness.store.snapshot()
    key = idem()
    harness.store.fail_next_commits = 1
    failed = await _submit(harness, session_id, key=key)
    assert failed.status_code == 500
    assert harness.store.snapshot() == before  # no orphan Run, Submission, outbox, or event
    retried = await _submit(harness, session_id, key=key)
    assert retried.status_code == 202  # the command was not lost: the retry succeeds
    assert len(_docs(harness, "runs")) == 1


async def test_cross_student_run_is_404(harness: Harness) -> None:
    session_id = await _session(harness)
    run_id = (await _submit(harness, session_id)).json()["runId"]
    beth = harness.auth("stu_beth")
    assert (await harness.client.get(f"/api/runs/{run_id}", headers=beth)).status_code == 404
    cancel = await harness.client.post(
        f"/api/runs/{run_id}/cancel", json={}, headers=harness.cmd("stu_beth")
    )
    assert cancel.status_code == 404


async def _cancel(h: Harness, run_id: str, key: str | None = None) -> Response:
    return await h.client.post(
        f"/api/runs/{run_id}/cancel", json={}, headers=h.cmd("stu_alex", key)
    )


async def test_cancel_queued_run(harness: Harness) -> None:
    session_id = await _session(harness)
    run_id = (await _submit(harness, session_id)).json()["runId"]
    response = await _cancel(harness, run_id)
    assert response.status_code == 202 and response.json()["status"] == "CANCELLED"
    session = await harness.client.get(
        f"/api/sessions/{session_id}", headers=harness.auth("stu_alex")
    )
    assert session.json()["activeRunId"] is None
    again = await _cancel(harness, run_id)
    assert again.status_code == 200 and again.json()["status"] == "CANCELLED"


async def test_cancel_racing_with_enqueue_is_consistent(harness: Harness) -> None:
    """The outbox entry was dispatched, then the student cancelled before the worker ran."""
    session_id = await _session(harness)
    run_id = (await _submit(harness, session_id)).json()["runId"]
    assert harness.queue.pending()  # dispatched right after commit
    await _cancel(harness, run_id)
    await harness.drain()  # the delivery arrives after cancellation
    run = await harness.client.get(f"/api/runs/{run_id}", headers=harness.auth("stu_alex"))
    assert run.json()["status"] == "CANCELLED"
    messages = await harness.client.get(
        f"/api/sessions/{session_id}/messages", headers=harness.auth("stu_alex")
    )
    assert messages.json()["messages"] == []  # no agent output for a cancelled run


async def test_cancel_terminal_run_is_409(harness: Harness) -> None:
    session_id = await _session(harness)
    run_id = (await _submit(harness, session_id)).json()["runId"]
    await harness.drain()
    response = await _cancel(harness, run_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUN_TERMINAL"


async def _wait_for_input(h: Harness, session_id: str) -> str:
    """Put the session's run into WAITING_INPUT the way a worker would (M2 OCR flow)."""
    run_id = (await _submit(h, session_id)).json()["runId"]
    path = f"students/stu_alex/runs/{run_id}"
    doc = h.store.raw(path)
    doc |= {
        "status": "WAITING_INPUT",
        "inputRequest": {
            "inputRequestId": "input_ocr_01",
            "kind": InputRequestKind.OCR_CONFIRMATION.value,
            "prompt": "Confirm the transcription",
        },
    }
    h.put_doc(path, doc)
    return run_id


async def test_run_input_only_for_matching_waiting_request(harness: Harness) -> None:
    session_id = await _session(harness)
    run_id = await _wait_for_input(harness, session_id)
    body = {"inputRequestId": "input_ocr_01", "value": {"confirmedText": "f(g(x))"}}
    stale = await harness.client.post(
        f"/api/runs/{run_id}/input",
        json={**body, "inputRequestId": "input_old"},
        headers=harness.cmd("stu_alex"),
    )
    assert stale.status_code == 409
    injected = await harness.client.post(
        f"/api/runs/{run_id}/input",
        json={**body, "value": {"confirmedText": "x", "score": 5}},
        headers=harness.cmd("stu_alex"),
    )
    assert injected.status_code == 400
    key = idem()
    ok = await harness.client.post(
        f"/api/runs/{run_id}/input", json=body, headers=harness.cmd("stu_alex", key)
    )
    assert ok.status_code == 202 and ok.json() == {"runId": run_id, "status": "QUEUED"}
    run = harness.store.raw(f"students/stu_alex/runs/{run_id}")
    assert run["dispatchGeneration"] == 2 and run["inputRequest"] is None
    assert (
        harness.store.raw("students/stu_alex/runInputs/input_ocr_01")["confirmedText"] == "f(g(x))"
    )
    replay = await harness.client.post(
        f"/api/runs/{run_id}/input", json=body, headers=harness.cmd("stu_alex", key)
    )
    assert replay.status_code == 202 and replay.headers["Idempotency-Replayed"] == "true"
    again = await harness.client.post(
        f"/api/runs/{run_id}/input", json=body, headers=harness.cmd("stu_alex")
    )
    assert again.status_code == 409  # no longer waiting: a second answer is stale


async def test_message_command_creates_hint_run(harness: Harness) -> None:
    session_id = await _session(harness)
    response = await harness.client.post(
        f"/api/sessions/{session_id}/messages",
        json={"text": "Can you help me find the inner function?"},
        headers=harness.cmd("stu_alex"),
    )
    assert response.status_code == 202
    run = harness.store.raw(f"students/stu_alex/runs/{response.json()['runId']}")
    assert run["kind"] == "HINT" and run["messageId"] == response.json()["messageId"]
