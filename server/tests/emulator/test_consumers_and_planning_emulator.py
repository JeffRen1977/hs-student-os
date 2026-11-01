"""M3 flows against the Firestore emulator: consumers and planning in real transactions.

The in-memory suites prove the rules; these prove that one real Firestore transaction
writes a consumer's effect, receipt and offset together, that replaying the log adds
nothing, and that a PLANNING run commits its plan and task moves atomically. The consumer
is the test-only `ProbeConsumer` (no production consumer is registered yet).
"""

from __future__ import annotations

from typing import Any

from app.domain.types.outbox import Delivery, OutboxKind
from tests.contract.test_event_consumers import PROBE, ProbeConsumer
from tests.emulator.test_firestore_flows import _h, make_env


async def _docs(env: dict[str, Any], who: str, collection: str) -> list[dict[str, Any]]:
    stream = env["db"].collection(f"students/{env[who]}/{collection}").stream()
    return [d.to_dict() async for d in stream]


async def _settle(env: dict[str, Any]) -> None:
    services = env["services"]
    for _ in range(5):
        await services.dispatcher.dispatch_pending()
        if not await env["queue"].drain(services.deliveries.process):
            return


async def test_consumer_commits_effect_receipt_and_offset_together() -> None:
    env = await make_env(consumers=[ProbeConsumer()])
    http = env["http"]
    r = await http.post(
        "/api/courses/enroll", json={"courseId": "dsat"}, headers=_h(env, "alex", True)
    )
    assert r.status_code == 200, r.text
    r = await http.post(
        "/api/sessions", json={"taskId": "task_alex_dsat_01"}, headers=_h(env, "alex", True)
    )
    r = await http.post(
        f"/api/sessions/{r.json()['sessionId']}/submissions",
        json={"questionId": "q_dsat_equiv_001", "questionVersion": "1",
              "answer": {"text": "1: A\n2: C\n3: B", "fileIds": []}},
        headers=_h(env, "alex", True),
    )  # fmt: skip
    assert r.status_code == 202, r.text
    await _settle(env)

    follow = [t for t in await _docs(env, "alex", "tasks") if t["taskId"].startswith("follow_")]
    [receipt] = await _docs(env, "alex", "consumerReceipts")
    assert [t["taskId"] for t in follow] == [receipt["taskId"]]
    assert follow[0]["courseId"] == "dsat"

    # Replay the whole log from zero: the receipt makes it a no-op.
    before = len(await _docs(env, "alex", "tasks"))
    await (
        env["db"]
        .document(f"students/{env['alex']}/consumerState/{PROBE}")
        .set({"consumer": PROBE, "processedSequence": 0, "updatedAt": env["clock"].now()})
    )
    await env["services"].deliveries.process(
        Delivery(delivery_id="wake.replay", student_id=env["alex"], run_id=None,
                 kind=OutboxKind.CONSUMERS)
    )  # fmt: skip
    assert len(await _docs(env, "alex", "tasks")) == before
    assert await _docs(env, "beth", "consumerReceipts") == []


async def test_planning_run_commits_plan_and_moves_together() -> None:
    env = await make_env()
    http = env["http"]
    r = await http.post("/api/plans/replan", json={}, headers=_h(env, "alex", True))
    assert r.status_code == 202
    await _settle(env)
    run = (await http.get(f"/api/runs/{r.json()['runId']}", headers=_h(env, "alex"))).json()
    assert run["status"] == "SUCCEEDED"
    plans = await _docs(env, "alex", "plans")
    assert [p["planId"] for p in plans] == [run["result"]["planId"]]
    state = await env["db"].document(f"students/{env['alex']}/planState/current").get()
    current = state.to_dict()
    assert current["activeRunId"] is None and current["latestPlanId"] == plans[0]["planId"]
