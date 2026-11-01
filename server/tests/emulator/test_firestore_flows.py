"""M1 flows against the real Firestore + Auth emulators (`make test-emulator`).

The contract/unit suites run the same repositories over the in-memory store. These tests
re-run the transaction-critical paths on Firestore itself, because a passing in-memory
transaction does not prove a real one behaves the same (CLAUDE.md §4.3).
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.firebase import create_async_firestore_client
from app.adapters.firestore.client_store import FirestoreDocumentStore
from app.adapters.queue.local_queue import LocalQueue
from app.adapters.seed_documents import build_seed_documents
from app.bootstrap import build_services
from app.config import Settings
from app.main import create_app
from app.registries.fixtures import load_seed_students
from tests.support import FakeClock, emulator_token, idem


@pytest.fixture
async def env() -> Any:
    return await make_env()


async def make_env(llm_provider: Any = None, consumers: Any = ()) -> dict[str, Any]:
    settings = Settings(_env_file=None, local_worker_enabled=False)  # type: ignore[call-arg]
    client = create_async_firestore_client(settings)
    # Unique student ids per test run: no dependence on emulator state or test order.
    suffix = secrets.token_hex(4)
    seeds = load_seed_students()
    docs: dict[str, dict[str, Any]] = {}
    clock = FakeClock()
    for path, data in build_seed_documents(seeds, now=clock.now()).items():
        new_path = path.replace("stu_alex", f"stu_alex_{suffix}").replace(
            "stu_beth", f"stu_beth_{suffix}"
        )
        new = {**data}
        for key in ("studentId",):
            if key in new:
                new[key] = new_path.split("/")[1]
        docs[new_path] = new
    batch = client.batch()
    for path, data in docs.items():
        batch.set(client.document(path), data)
    await batch.commit()
    queue = LocalQueue()
    services = build_services(
        settings,
        store=FirestoreDocumentStore(client),
        clock=clock,
        queue=queue,
        llm_provider=llm_provider,
        consumers=consumers,
    )
    app = create_app(settings, services)
    http = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return {"alex": f"stu_alex_{suffix}", "beth": f"stu_beth_{suffix}", "http": http,
            "services": services, "queue": queue, "clock": clock, "db": client}  # fmt: skip


def _h(env: dict[str, Any], who: str, key: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {emulator_token(env[who], now=env['clock'].now())}"}
    return headers | ({"Idempotency-Key": idem()} if key else {})


async def test_isolation_and_twin_concurrency(env: dict[str, Any]) -> None:
    http = env["http"]
    alex = await http.get("/api/twin", headers=_h(env, "alex"))
    assert alex.status_code == 200 and alex.json()["studentId"] == env["alex"]
    headers = _h(env, "alex") | {"If-Match": alex.headers["ETag"]}
    a, b = await asyncio.gather(
        http.patch("/api/twin", json={"profile": {"grade": 12}}, headers=headers),
        http.patch("/api/twin", json={"profile": {"grade": 10}}, headers=headers),
    )
    assert sorted([a.status_code, b.status_code]) == [200, 409]
    task_id = "task_beth_calc_01"
    assert (await http.get(f"/api/tasks/{task_id}", headers=_h(env, "alex"))).status_code == 404


async def test_enrollment_session_command_and_worker(env: dict[str, Any]) -> None:
    http, services = env["http"], env["services"]
    starts = await asyncio.gather(
        *(
            http.post(
                "/api/sessions", json={"taskId": "task_alex_calc_01"}, headers=_h(env, "alex", True)
            )
            for _ in range(3)
        )
    )
    assert len({r.json()["sessionId"] for r in starts}) == 1
    session_id = starts[0].json()["sessionId"]
    assert (
        await http.post(
            "/api/courses/unenroll", json={"courseId": "calc_bc"}, headers=_h(env, "alex", True)
        )
    ).status_code == 409

    key = idem()
    headers = _h(env, "alex") | {"Idempotency-Key": key}
    body = {"text": "Where do I start?"}
    first, dup = await asyncio.gather(
        http.post(f"/api/sessions/{session_id}/messages", json=body, headers=headers),
        http.post(f"/api/sessions/{session_id}/messages", json=body, headers=headers),
    )
    assert first.status_code == dup.status_code == 202
    assert first.json()["runId"] == dup.json()["runId"]
    other = await http.post(
        f"/api/sessions/{session_id}/messages", json=body, headers=_h(env, "alex", True)
    )
    assert other.status_code == 409

    await services.dispatcher.dispatch_pending()
    await env["queue"].drain(services.run_execution.process)
    run = await http.get(f"/api/runs/{first.json()['runId']}", headers=_h(env, "alex"))
    assert run.json()["status"] == "SUCCEEDED"
    messages = await http.get(f"/api/sessions/{session_id}/messages", headers=_h(env, "alex"))
    assert [m["role"] for m in messages.json()["messages"]] == ["student", "agent"]
