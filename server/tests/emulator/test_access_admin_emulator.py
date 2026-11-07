"""Step 42 against the real Firestore emulator (`make test-emulator`).

An access change is a read-modify-write of `access/current` plus an audit entry and a
student event. These tests check, on Firestore itself, that the pieces commit together and
that two concurrent changes to one student's access both survive (neither overwrites the
other), with distinct audit entries and event sequences.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.emulator.test_firestore_flows import make_env
from tests.support import emulator_token, idem

ADMIN = "admin_platform"


@pytest.fixture
async def env() -> Any:
    return await make_env()


def _admin(env: dict[str, Any]) -> dict[str, str]:
    token = emulator_token(ADMIN, now=env["clock"].now())
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": idem()}


async def _docs(env: dict[str, Any], sid: str, collection: str) -> list[dict[str, Any]]:
    snaps = env["db"].collection(f"students/{sid}/{collection}").stream()
    return [s.to_dict() async for s in snaps]


async def test_grant_commits_record_audit_and_event_then_enroll(env: dict[str, Any]) -> None:
    http, beth = env["http"], env["beth"]
    path = f"/api/admin/students/{beth}/access"
    body = {"courseId": "dsat", "reason": "Pilot."}
    r = await http.post(f"{path}/grant", json=body, headers=_admin(env))
    assert r.status_code == 200, r.text
    audit_id = r.json()["auditId"]

    access = (await env["db"].document(f"students/{beth}/access/current").get()).to_dict()
    assert "dsat" in access["courses"] and access["updatedBy"] == ADMIN
    [audit] = await _docs(env, beth, "accessAudit")
    assert audit["auditId"] == audit_id and audit["reason"] == "Pilot."
    events = [e for e in await _docs(env, beth, "events") if e["type"] == "access.changed"]
    assert len(events) == 1 and events[0]["payload"] == {"courseId": "dsat", "change": "granted"}

    token = emulator_token(beth, now=env["clock"].now())
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": idem()}
    r = await http.post("/api/courses/enroll", json={"courseId": "dsat"}, headers=headers)
    assert r.status_code == 200, r.text


async def test_concurrent_changes_to_one_student_both_survive(env: dict[str, Any]) -> None:
    http, beth = env["http"], env["beth"]
    path = f"/api/admin/students/{beth}/access"
    grant = {"courseId": "dsat", "reason": "a"}
    revoke = {"courseId": "calc_bc", "reason": "b"}
    a, b = await asyncio.gather(
        http.post(f"{path}/grant", json=grant, headers=_admin(env)),
        http.post(f"{path}/revoke", json=revoke, headers=_admin(env)),
    )
    assert (a.status_code, b.status_code) == (200, 200), (a.text, b.text)
    access = (await env["db"].document(f"students/{beth}/access/current").get()).to_dict()
    assert access["courses"] == ["dsat"] and access["apCourses"] == []
    assert sorted(x["change"] for x in await _docs(env, beth, "accessAudit")) == [
        "grant",
        "revoke",
    ]
    seqs = [e["sequence"] for e in await _docs(env, beth, "events")]
    assert len(seqs) == len(set(seqs))
    # Alex was never touched.
    assert await _docs(env, env["alex"], "accessAudit") == []
