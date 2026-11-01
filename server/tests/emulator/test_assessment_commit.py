"""M2 flows against the Firestore emulator: the atomic assessment commit and complete.

The in-memory suites prove the logic; these prove that one real Firestore transaction
writes Assessment + mastery + Run terminal state + events together, and that a replayed or
stale commit writes nothing.
"""

from __future__ import annotations

from typing import Any

from app.domain.run_execution import LeaseGrant
from tests.contract.test_assessment_flow import CORRECT, SUBMISSION
from tests.emulator.test_firestore_flows import _h, make_env
from tests.support import ScriptedProvider


async def _count(env: dict[str, Any], who: str, collection: str) -> int:
    docs = env["db"].collection(f"students/{env[who]}/{collection}").stream()
    return len([d async for d in docs])


async def test_assessment_commit_is_atomic_and_fenced() -> None:
    provider = ScriptedProvider(CORRECT, CORRECT)
    env = await make_env(provider)
    http, services = env["http"], env["services"]
    r = await http.post(
        "/api/sessions", json={"taskId": "task_alex_calc_01"}, headers=_h(env, "alex", True)
    )
    session_id = r.json()["sessionId"]
    r = await http.post(
        f"/api/sessions/{session_id}/submissions", json=SUBMISSION, headers=_h(env, "alex", True)
    )
    run_id = r.json()["runId"]

    worker = services.run_execution
    actor = worker.actor_for(env["alex"])
    old = await worker.acquire(actor, run_id)
    assert isinstance(old, LeaseGrant)
    old_output = await worker._executor.execute(old.request)
    env["clock"].advance(seconds=services.settings.run_lease_seconds + 1)
    new = await worker.acquire(actor, run_id)
    assert isinstance(new, LeaseGrant)
    assert await worker.commit(actor, run_id, old.token, old_output) is False
    assert await _count(env, "alex", "assessments") == 0

    new_output = await worker._executor.execute(new.request)
    assert await worker.commit(actor, run_id, new.token, new_output) is True
    assert await worker.commit(actor, run_id, new.token, new_output) is False
    assert await _count(env, "alex", "assessments") == 1
    assert await _count(env, "alex", "mastery") == 2

    r = await http.post(
        f"/api/sessions/{session_id}/complete", json={}, headers=_h(env, "alex", True)
    )
    assert r.status_code == 200 and r.json()["status"] == "COMPLETED"
    r = await http.get(f"/api/assessments?sessionId={session_id}", headers=_h(env, "beth"))
    assert r.status_code == 404
