"""Step 31: metrics, simulated alerts, backup/restore consistency, deletion and retention.

Alex answers a Digital SAT set (key-scored, no model), completes the session and replans,
so his record has a task, session, submission, run, assessment, mastery, plan and events.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import pytest

from app.adapters.firestore.backup import (
    RestoreRefused,
    decode_backup,
    delete_student,
    encode_backup,
    export_student,
    restore_student,
    verify_student,
)
from app.adapters.firestore.memory_store import MemoryDocumentStore
from app.adapters.firestore.run_repository import run_to_doc
from app.adapters.observability import InMemoryMetrics
from app.adapters.seed_documents import build_platform_documents
from app.domain.types.run import Run, RunError, RunKind, RunStatus
from app.registries.fixtures import load_platform_fixture
from tests.support import Harness, build_harness

ALEX, BETH = "stu_alex", "stu_beth"
SAT_TASK = "task_alex_dsat_01"


@pytest.fixture
def metrics() -> InMemoryMetrics:
    return InMemoryMetrics()


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch, metrics: InMemoryMetrics) -> Harness:
    return build_harness(
        clean_env,
        metrics=metrics,
        alert_outbox_backlog=1,
        alert_failed_runs_per_hour=2,
        alert_budget_overruns_per_hour=1,
    )


async def ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()


async def sat_practice(h: Harness, key: str | None = None) -> dict[str, Any]:
    session = await ok(
        await h.client.post("/api/sessions", json={"taskId": SAT_TASK}, headers=h.cmd(ALEX)), 201
    )
    act = session["activity"]
    body = {"questionId": act["questionId"], "questionVersion": act["questionVersion"],
            "answer": {"text": "1: A\n2: C\n3: B", "fileIds": []}}  # fmt: skip
    url = f"/api/sessions/{session['sessionId']}/submissions"
    headers = h.cmd(ALEX, key)
    await ok(await h.client.post(url, json=body, headers=headers), 202)
    await ok(await h.client.post(url, json=body, headers=headers), 202)  # retried request
    await h.settle()
    await ok(
        await h.client.post(
            f"/api/sessions/{session['sessionId']}/complete", json={}, headers=h.cmd(ALEX)
        )
    )
    await ok(await h.client.post("/api/plans/replan", json={}, headers=h.cmd(ALEX)), 202)
    await h.settle()
    return dict(session)


async def snapshot_api(h: Harness, session_id: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path in (
        "/api/twin",
        "/api/tasks",
        f"/api/sessions/{session_id}",
        f"/api/assessments?sessionId={session_id}",
        "/api/mastery?courseId=dsat",
        "/api/plans/latest",
        "/api/events?after=0&limit=100",
    ):
        out[path] = await ok(await h.client.get(path, headers=h.auth(ALEX)))
    return out


# ---- Metrics ------------------------------------------------------------------------


async def test_metrics_cover_latency_failures_and_duplicate_suppression(
    h: Harness, metrics: InMemoryMetrics
) -> None:
    await sat_practice(h, key="idk_fixed_for_retry_0001")
    assert metrics.total("duplicate.suppressed", source="idempotency") == 1
    assert metrics.total("run.committed", kind="ASSESS_SUBMISSION") == 1
    assert metrics.observations["run.execute_ms"]
    assert metrics.observations["http.latency_ms"]
    # A duplicate queue delivery of the finished run is suppressed and counted.
    run_path = next(
        p for p in h.store.paths(f"students/{ALEX}/runs/")
        if h.store.raw(p)["kind"] == "ASSESS_SUBMISSION"
    )  # fmt: skip
    run_id = h.store.raw(run_path)["runId"]
    from app.domain.types.outbox import Delivery

    await h.services.deliveries.process(
        Delivery(delivery_id=f"{run_id}.g1", student_id=ALEX, run_id=run_id)
    )
    assert metrics.total("duplicate.suppressed", source="delivery") == 1


# ---- Alerts -------------------------------------------------------------------------


def failed_run(run_id: str, code: str, at: datetime) -> dict[str, Any]:
    run = Run(
        run_id=run_id, student_id=BETH, session_id="ses_x", status=RunStatus.FAILED,
        kind=RunKind.ASSESS_SUBMISSION, error=RunError(code=code, retryable=False),
        created_at=at, updated_at=at,
    )  # fmt: skip
    return run_to_doc(run)


async def test_simulated_alerts_fire_and_clear(
    h: Harness, metrics: InMemoryMetrics, caplog: pytest.LogCaptureFixture
) -> None:
    check = h.services.ops_monitor.check
    assert not any(s.firing for s in await check())

    # Outbox backlog: the queue is down, so the command's delivery stays pending.
    class QueueDown:
        async def enqueue(self, delivery: object) -> None:
            raise ConnectionError("queue unavailable")

    queue = h.services.dispatcher._queue
    h.services.dispatcher._queue = QueueDown()  # type: ignore[assignment]
    replan = await h.client.post("/api/plans/replan", json={}, headers=h.cmd(ALEX))
    assert replan.status_code == 202
    assert not any(s.firing for s in await check())  # fresh entries are not a backlog
    h.clock.advance(minutes=6)
    caplog.set_level(logging.ERROR, logger="app.domain.ops_monitor")
    firing = {s.alert: s for s in await check() if s.firing}
    assert set(firing) == {"outbox_backlog"} and firing["outbox_backlog"].observed == 1
    [alert] = [r for r in caplog.records if r.getMessage() == "alert_firing"]
    assert alert.levelname == "ERROR" and alert.__dict__["alert"] == "outbox_backlog"

    # Worker failures and budget overruns in the last hour.
    now = h.clock.now()
    h.put_doc(f"students/{BETH}/runs/run_f1", failed_run("run_f1", "EXECUTION_FAILED", now))
    h.put_doc(f"students/{BETH}/runs/run_f2", failed_run("run_f2", "BUDGET_EXCEEDED", now))
    firing = {s.alert for s in await check() if s.firing}
    assert firing == {"outbox_backlog", "worker_failures", "budget_overruns"}
    assert metrics.total("ops.alert", alert="budget_overruns") == 1

    # Recovery: the queue is back and the dispatcher drains the backlog; an hour later the
    # failures age out.
    h.services.dispatcher._queue = queue
    await h.settle()
    h.clock.advance(hours=1, minutes=1)
    assert not any(s.firing for s in await check())


async def test_ops_check_route(clean_env: pytest.MonkeyPatch) -> None:
    from httpx import ASGITransport, AsyncClient
    from pydantic import SecretStr

    from app.workers.run_worker import create_worker_app

    h = build_harness(clean_env, worker_service_token=SecretStr("local-worker-token-123"))
    client = AsyncClient(
        transport=ASGITransport(app=create_worker_app(h.services.settings, h.services)),
        base_url="http://worker",
    )
    service = {"Authorization": "Bearer local-worker-token-123"}
    for path in ("/internal/ops/check", "/internal/retention/events"):
        assert (await client.post(path, headers=h.auth(ALEX))).status_code == 401
    body = (await client.post("/internal/ops/check", headers=service)).json()
    assert {a["alert"] for a in body["alerts"]} == {
        "outbox_backlog", "worker_failures", "budget_overruns"
    }  # fmt: skip
    assert (await client.post("/internal/retention/events", headers=service)).json() == {"count": 0}


# ---- Backup / restore -----------------------------------------------------------------


async def test_backup_restores_into_a_separate_store_with_every_link_intact(
    clean_env: pytest.MonkeyPatch, h: Harness
) -> None:
    session = await sat_practice(h)
    assert await verify_student(h.store, ALEX) == []
    before = await snapshot_api(h, session["sessionId"])
    assert before[f"/api/assessments?sessionId={session['sessionId']}"]["assessments"]

    text = encode_backup(await export_student(h.store, ALEX, now=h.clock.now()))
    assert "1: A" in text  # backups hold the record itself, which is why they are protected

    # A separate environment: platform data only, then the student's backup.
    target = MemoryDocumentStore(
        build_platform_documents(load_platform_fixture(), now=h.clock.now())
    )
    restored = await restore_student(target, decode_backup(text))
    assert restored == len(await target.read_subtree(f"students/{ALEX}")) + 1  # + identity
    assert await verify_student(target, ALEX) == []
    assert await target.read_subtree(f"students/{BETH}") == {}  # nothing else came along

    other = build_harness(clean_env, store=target)
    other.clock.set(h.clock.now())
    assert await snapshot_api(other, session["sessionId"]) == before

    with pytest.raises(RestoreRefused, match="already exists"):
        await restore_student(target, decode_backup(text))


async def test_restore_rejects_documents_of_other_students(h: Harness) -> None:
    backup = await export_student(h.store, ALEX, now=h.clock.now())
    tampered = {**backup.documents, f"students/{BETH}/tasks/t": {"taskId": "t"}}
    target = MemoryDocumentStore()
    with pytest.raises(RestoreRefused, match="outside"):
        await restore_student(target, type(backup)(student_id=ALEX,
                              exported_at=backup.exported_at, documents=tampered))  # fmt: skip


async def test_verify_reports_broken_links(h: Harness) -> None:
    session = await sat_practice(h)
    h.store._data.pop(f"students/{ALEX}/sessions/{session['sessionId']}")
    issues = await verify_student(h.store, ALEX)
    assert any("session missing" in i for i in issues)
    first_event = h.store.paths(f"students/{ALEX}/events/")[0]
    h.store._data.pop(first_event)
    assert any(i.startswith("events:") for i in await verify_student(h.store, ALEX))


# ---- Deletion and retention ------------------------------------------------------------


async def test_deleting_a_student_leaves_nothing_scannable_and_blocks_restore(
    h: Harness,
) -> None:
    await sat_practice(h)
    await h.client.post("/api/plans/replan", json={}, headers=h.cmd(ALEX))  # pending work
    backup = await export_student(h.store, ALEX, now=h.clock.now())
    count = await delete_student(h.store, ALEX, now=h.clock.now())
    assert count == len(backup.documents)
    assert h.store.paths(f"students/{ALEX}") == []
    assert h.store.paths("identities/") == [p for p in h.store.paths("identities/")
                                             if h.store.raw(p)["studentId"] != ALEX]  # fmt: skip
    assert h.store.raw(f"deletedStudents/{ALEX}") == {"studentId": ALEX, "deletedAt": h.clock.now()}
    ops = h.services.operations
    far = datetime(2100, 1, 1, tzinfo=UTC)
    assert all(e.student_id != ALEX for e in await ops.pending_outbox(500))
    assert ALEX not in await ops.due_plan_schedules(due_before=far, limit=500)
    stalled = await ops.stalled_runs(queued_before=far, lease_expired_before=far, limit=500)
    assert all(r.student_id != ALEX for r in stalled)
    assert all(s != ALEX for s, _ in await ops.due_reminders(
        due_before=far, claim_expired_before=far, limit=500))  # fmt: skip
    assert ALEX not in await ops.student_ids(after=None, limit=500)
    # Beth's record is untouched; an old backup of Alex can never bring him back.
    assert await verify_student(h.store, BETH) == []
    with pytest.raises(RestoreRefused, match="deleted"):
        await restore_student(h.store, backup)


async def test_event_retention_purges_old_events_and_expires_old_cursors(h: Harness) -> None:
    await sat_practice(h)
    events = (await ok(await h.client.get("/api/events?after=0", headers=h.auth(ALEX))))["events"]
    last = events[-1]["sequence"]
    h.clock.advance(days=181)
    # One new event after the cut-off: it is kept.
    await ok(await h.client.post("/api/plans/replan", json={}, headers=h.cmd(ALEX)), 202)
    purged = await h.services.event_retention.purge()
    assert purged >= last  # Alex's old events (and Beth's, if any) are gone
    gone = await h.client.get("/api/events?after=0", headers=h.auth(ALEX))
    assert gone.status_code == 410
    kept = await ok(await h.client.get(f"/api/events?after={last}", headers=h.auth(ALEX)))
    assert kept["events"] and kept["events"][0]["sequence"] == last + 1
    # Assessments, mastery and plans are the record: retention never touches them.
    assert h.store.paths(f"students/{ALEX}/assessments/")
    assert await verify_student(h.store, ALEX) == []
    assert await h.services.event_retention.purge() == 0  # idempotent
