"""Step 15: outbox dispatch, leases + fencing tokens, crash recovery, synthetic execution."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.adapters.execution.synthetic import SYNTHETIC_LABEL, SyntheticExecutor
from app.adapters.queue.local_queue import LocalQueue
from app.bootstrap import build_services
from app.domain.ports.execution import ExecutionOutput, ExecutionRequest, RetryableExecutionError
from app.domain.run_execution import LeaseGrant, ProcessResult
from app.domain.types.outbox import Delivery
from app.workers.run_worker import create_worker_app
from tests.support import Harness, build_harness, harness_settings

SID = "stu_alex"


async def _hint(h: Harness, text: str = "Where do I start?") -> tuple[str, str]:
    session = await h.client.post(
        "/api/sessions", json={"taskId": "task_alex_calc_01"}, headers=h.cmd(SID)
    )
    session_id = session.json()["sessionId"]
    response = await h.client.post(
        f"/api/sessions/{session_id}/messages", json={"text": text}, headers=h.cmd(SID)
    )
    assert response.status_code == 202
    return session_id, response.json()["runId"]


def _run(h: Harness, run_id: str) -> dict[str, Any]:
    doc: dict[str, Any] = h.store.raw(f"students/{SID}/runs/{run_id}")
    return doc


def _events(h: Harness) -> list[str]:
    docs = [h.store.raw(p) for p in h.store.paths(f"students/{SID}/events/")]
    return [d["type"] for d in sorted(docs, key=lambda d: d["sequence"])]


def _agent_messages(h: Harness) -> list[dict[str, Any]]:
    docs = [h.store.raw(p) for p in h.store.paths(f"students/{SID}/messages/")]
    return [d for d in docs if d["role"] == "agent"]


def _delivery(run_id: str, generation: int = 1) -> Delivery:
    return Delivery(delivery_id=f"{run_id}.g{generation}", student_id=SID, run_id=run_id)


async def test_happy_path_is_labeled_synthetic(harness: Harness) -> None:
    session_id, run_id = await _hint(harness)
    assert await harness.drain() == 1
    run = _run(harness, run_id)
    assert run["status"] == "SUCCEEDED" and run["attemptCount"] == 1
    assert run["result"]["assessmentId"] is None  # synthetic mode never grades
    [agent] = _agent_messages(harness)
    assert agent["synthetic"] is True and agent["text"].startswith(SYNTHETIC_LABEL)
    messages = await harness.client.get(
        f"/api/sessions/{session_id}/messages", headers=harness.auth(SID)
    )
    assert [(m["role"], m["synthetic"]) for m in messages.json()["messages"]] == [
        ("student", False),
        ("agent", True),
    ]
    session = await harness.client.get(f"/api/sessions/{session_id}", headers=harness.auth(SID))
    assert session.json()["activeRunId"] is None
    assert session.json()["completion"]["reason"] == "accepted_assessment_required"
    assert _events(harness) == ["session.started", "run.queued", "run.started", "run.completed"]


async def test_restart_after_commit_before_dispatch(
    harness: Harness, clean_env: pytest.MonkeyPatch
) -> None:
    async def lost(_d: Delivery) -> None:
        raise ConnectionError("queue unreachable")

    harness.queue.enqueue = lost  # type: ignore[method-assign]
    _, run_id = await _hint(harness)  # immediate dispatch fails; the command still succeeded
    assert _run(harness, run_id)["status"] == "QUEUED"
    [entry] = [harness.store.raw(p) for p in harness.store.paths(f"students/{SID}/outbox/")]
    assert entry["status"] == "pending"

    # "Restart": a new process with a fresh queue over the same durable store.
    queue = LocalQueue()
    services = build_services(
        harness_settings(clean_env), store=harness.store, clock=harness.clock, queue=queue
    )
    assert await services.dispatcher.dispatch_pending() == 1
    assert await queue.drain(services.run_execution.process) == 1
    assert _run(harness, run_id)["status"] == "SUCCEEDED"


async def test_crash_between_enqueue_and_ack_duplicates_harmlessly(harness: Harness) -> None:
    original = harness.queue.enqueue

    async def enqueue_then_crash(delivery: Delivery) -> None:
        await original(delivery)
        harness.store.fail_next_commits = 1  # the "mark dispatched" commit is lost

    harness.queue.enqueue = enqueue_then_crash  # type: ignore[method-assign]
    _, run_id = await _hint(harness)
    assert harness.store.raw(f"students/{SID}/outbox/{run_id}.g1")["status"] == "pending"
    await harness.queue.drain(harness.services.run_execution.process)  # first delivery runs
    harness.queue.enqueue = original  # type: ignore[method-assign]
    assert await harness.services.dispatcher.dispatch_pending() == 1  # re-enqueued (duplicate)
    await harness.queue.drain(harness.services.run_execution.process)
    assert len(_agent_messages(harness)) == 1  # the duplicate had no effect
    assert _events(harness).count("run.completed") == 1
    assert harness.store.raw(f"students/{SID}/outbox/{run_id}.g1")["status"] == "dispatched"


async def test_duplicate_delivery_is_idempotent(harness: Harness) -> None:
    _, run_id = await _hint(harness)
    worker = harness.services.run_execution
    assert await worker.process(_delivery(run_id)) is ProcessResult.DONE
    before = harness.store.snapshot()
    assert await worker.process(_delivery(run_id)) is ProcessResult.DONE
    assert harness.store.snapshot() == before


async def test_live_lease_makes_other_delivery_retry(harness: Harness) -> None:
    _, run_id = await _hint(harness)
    worker = harness.services.run_execution
    grant = await worker.acquire(worker.actor_for(SID), run_id)
    assert isinstance(grant, LeaseGrant)
    assert await worker.process(_delivery(run_id)) is ProcessResult.RETRY


async def test_worker_crash_lease_expiry_requeue(harness: Harness) -> None:
    _, run_id = await _hint(harness)
    await harness.services.dispatcher.dispatch_pending()
    harness.queue._pending.clear()  # the in-flight delivery dies with the worker
    worker = harness.services.run_execution
    grant = await worker.acquire(worker.actor_for(SID), run_id)
    assert isinstance(grant, LeaseGrant) and grant.token == 1
    # ...worker crashes here: no commit, no ack.
    assert await harness.services.recovery.requeue_stalled() == 0  # lease still live
    harness.clock.advance(seconds=harness.services.settings.run_lease_seconds + 1)
    assert await harness.services.recovery.requeue_stalled() == 1
    assert _run(harness, run_id)["dispatchGeneration"] == 2
    assert await harness.drain() == 1
    run = _run(harness, run_id)
    assert run["status"] == "SUCCEEDED"
    assert run["attemptCount"] == 2 and run["leaseFencingToken"] == 2
    assert _events(harness).count("run.started") == 1  # one start event, not per attempt


async def test_stale_worker_cannot_commit(harness: Harness) -> None:
    _, run_id = await _hint(harness)
    worker = harness.services.run_execution
    actor = worker.actor_for(SID)
    old = await worker.acquire(actor, run_id)
    assert isinstance(old, LeaseGrant)
    harness.clock.advance(seconds=harness.services.settings.run_lease_seconds + 1)
    new = await worker.acquire(actor, run_id)
    assert isinstance(new, LeaseGrant) and new.token == old.token + 1
    stale = ExecutionOutput(agent_text="from the stale worker", model_version="x", synthetic=True)
    assert await worker.commit(actor, run_id, old.token, stale) is False
    fresh = ExecutionOutput(agent_text="from the new worker", model_version="x", synthetic=True)
    assert await worker.commit(actor, run_id, new.token, fresh) is True
    assert [m["text"] for m in _agent_messages(harness)] == ["from the new worker"]
    assert await worker.commit(actor, run_id, new.token, fresh) is False  # terminal now


async def test_cancel_commit_race_cancel_first(harness: Harness) -> None:
    _, run_id = await _hint(harness)
    worker = harness.services.run_execution
    actor = worker.actor_for(SID)
    grant = await worker.acquire(actor, run_id)
    assert isinstance(grant, LeaseGrant)
    cancel = await harness.client.post(
        f"/api/runs/{run_id}/cancel", json={}, headers=harness.cmd(SID)
    )
    assert cancel.status_code == 202 and cancel.json()["status"] == "RUNNING"  # flagged only
    output = ExecutionOutput(agent_text="late answer", model_version="x", synthetic=True)
    assert await worker.commit(actor, run_id, grant.token, output) is True
    assert _run(harness, run_id)["status"] == "CANCELLED"
    assert _agent_messages(harness) == []


async def test_cancel_commit_race_commit_first(harness: Harness) -> None:
    _, run_id = await _hint(harness)
    await harness.drain()
    cancel = await harness.client.post(
        f"/api/runs/{run_id}/cancel", json={}, headers=harness.cmd(SID)
    )
    assert cancel.status_code == 409 and _run(harness, run_id)["status"] == "SUCCEEDED"


async def test_cancel_requested_on_dead_worker_is_finalized(harness: Harness) -> None:
    _, run_id = await _hint(harness)
    worker = harness.services.run_execution
    assert isinstance(await worker.acquire(worker.actor_for(SID), run_id), LeaseGrant)
    await harness.client.post(f"/api/runs/{run_id}/cancel", json={}, headers=harness.cmd(SID))
    harness.clock.advance(seconds=harness.services.settings.run_lease_seconds + 1)
    await harness.services.recovery.requeue_stalled()
    await harness.drain()
    assert _run(harness, run_id)["status"] == "CANCELLED"


class FlakyExecutor:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def execute(self, request: ExecutionRequest) -> ExecutionOutput:
        self.calls += 1
        if self.calls <= self.failures:
            raise RetryableExecutionError("provider timeout")
        return await SyntheticExecutor().execute(request)


async def test_retryable_error_releases_lease_then_succeeds(clean_env: pytest.MonkeyPatch) -> None:
    h = build_harness(clean_env, executor=FlakyExecutor(failures=1))
    _, run_id = await _hint(h)
    await h.services.dispatcher.dispatch_pending()
    assert await h.queue.drain(h.services.run_execution.process) == 0  # RETRY, kept queued
    assert _run(h, run_id)["status"] == "RUNNING"
    assert await h.queue.drain(h.services.run_execution.process) == 1  # no wait for expiry
    assert _run(h, run_id)["status"] == "SUCCEEDED" and _run(h, run_id)["attemptCount"] == 2


async def test_retries_exhausted_fails_with_safe_error(clean_env: pytest.MonkeyPatch) -> None:
    h = build_harness(clean_env, executor=FlakyExecutor(failures=99))
    session_id, run_id = await _hint(h)
    await h.services.dispatcher.dispatch_pending()
    for _ in range(5):
        await h.queue.drain(h.services.run_execution.process)
    run = await h.client.get(f"/api/runs/{run_id}", headers=h.auth(SID))
    assert run.json()["status"] == "FAILED"
    assert run.json()["error"] == {"code": "EXECUTION_RETRIES_EXHAUSTED", "retryable": False}
    session = await h.client.get(f"/api/sessions/{session_id}", headers=h.auth(SID))
    assert session.json()["activeRunId"] is None  # the slot is freed for a new command


class CrashingExecutor:
    async def execute(self, request: ExecutionRequest) -> ExecutionOutput:
        raise RuntimeError("provider said: secret internal detail")


async def test_unexpected_error_fails_without_leaking(clean_env: pytest.MonkeyPatch) -> None:
    h = build_harness(clean_env, executor=CrashingExecutor())
    _, run_id = await _hint(h)
    await h.drain()
    run = _run(h, run_id)
    assert run["status"] == "FAILED" and run["error"] == {
        "code": "EXECUTION_FAILED",
        "retryable": False,
    }
    assert "secret" not in str(h.store.snapshot())


async def test_lost_enrollment_or_access_fails_the_run(harness: Harness) -> None:
    _, run_id = await _hint(harness)
    harness.put_doc(
        f"students/{SID}/enrollments/calc_bc",
        {
            "courseId": "calc_bc",
            "status": "unenrolled",
            "enrolledAt": harness.clock.now(),
            "unenrolledAt": harness.clock.now(),
        },
    )
    await harness.drain()
    assert _run(harness, run_id)["error"] == {"code": "COURSE_NOT_ENROLLED", "retryable": False}
    assert _agent_messages(harness) == []


async def test_stuck_queued_run_is_redispatched(harness: Harness) -> None:
    _, run_id = await _hint(harness)
    harness.queue._pending.clear()  # the queue lost the message after it was marked dispatched
    harness.clock.advance(seconds=harness.services.settings.run_requeue_after_seconds - 1)
    assert await harness.services.recovery.requeue_stalled() == 0
    harness.clock.advance(seconds=2)
    assert await harness.services.recovery.requeue_stalled() == 1
    await harness.drain()
    assert _run(harness, run_id)["status"] == "SUCCEEDED"


# ---- Worker HTTP surface -------------------------------------------------------------


@pytest.fixture
def worker_client(clean_env: pytest.MonkeyPatch) -> tuple[Harness, AsyncClient]:
    h = build_harness(clean_env, worker_service_token=SecretStr("local-worker-token-123"))
    app = create_worker_app(h.services.settings, h.services)
    return h, AsyncClient(transport=ASGITransport(app=app), base_url="http://worker")


async def test_worker_requires_service_identity(worker_client: tuple[Harness, AsyncClient]) -> None:
    h, client = worker_client
    _, run_id = await _hint(h)
    body = {"deliveryId": f"{run_id}.g1", "studentId": SID, "runId": run_id}
    assert (await client.post("/internal/runs/execute", json=body)).status_code == 401
    student = await client.post("/internal/runs/execute", json=body, headers=h.auth(SID))
    assert student.status_code == 401  # a student token is never a service identity
    ok = await client.post(
        "/internal/runs/execute",
        json=body,
        headers={"Authorization": "Bearer local-worker-token-123"},
    )
    assert ok.status_code == 200 and ok.json() == {"result": "done"}
    assert _run(h, run_id)["status"] == "SUCCEEDED"


async def test_worker_returns_503_while_lease_is_held(
    worker_client: tuple[Harness, AsyncClient],
) -> None:
    h, client = worker_client
    _, run_id = await _hint(h)
    worker = h.services.run_execution
    await worker.acquire(worker.actor_for(SID), run_id)
    response = await client.post(
        "/internal/runs/execute",
        json={"deliveryId": f"{run_id}.g1", "studentId": SID, "runId": run_id},
        headers={"Authorization": "Bearer local-worker-token-123"},
    )
    assert response.status_code == 503 and response.json() == {"result": "retry"}


async def test_internal_routes_are_not_on_the_student_api(harness: Harness) -> None:
    response = await harness.client.post(
        "/internal/runs/execute", json={}, headers=harness.auth(SID)
    )
    assert response.status_code == 404


async def test_consumer_endpoint_requires_service_identity(
    worker_client: tuple[Harness, AsyncClient],
) -> None:
    h, client = worker_client
    body = {"deliveryId": "wake.evt_x", "studentId": SID}
    assert (await client.post("/internal/consumers/process", json=body)).status_code == 401
    student = await client.post("/internal/consumers/process", json=body, headers=h.auth(SID))
    assert student.status_code == 401
    ok = await client.post(
        "/internal/consumers/process",
        json=body,
        headers={"Authorization": "Bearer local-worker-token-123"},
    )
    assert ok.status_code == 200 and ok.json() == {"result": "done"}
    bad = await client.post(
        "/internal/consumers/process",
        json={**body, "runId": "run_1"},
        headers={"Authorization": "Bearer local-worker-token-123"},
    )
    assert bad.status_code == 400  # wakes carry ids only, never a run or payload
