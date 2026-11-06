"""Step 36: scoped parent summaries.

- A parent is a separate identity; links exist only when a student creates an invite and
  the parent redeems it. The student can revoke at any time.
- Every parent read re-checks the link and scope: revoked, foreign or unknown → 404.
- The summary is a field-level projection: no chats, answers, feedback, essays or
  admissions data, whatever the student has stored.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.support import Harness, build_harness, idem

ALEX, BETH = "stu_alex", "stu_beth"
PARENT_A, PARENT_B = "parent_alex", "parent_other"
FORBIDDEN_KEYS = (
    "messages", "submissions", "answer", "feedback", "essay", "facts", "evidenceRefs",
    "entitlements", "email", "sessionId", "rubricResults", "payload", "text",
)  # fmt: skip


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch) -> Harness:
    return build_harness(clean_env)


async def post(h: Harness, path: str, uid: str, body: dict[str, Any], status: int,
               key: str | None = None) -> Any:  # fmt: skip
    r = await h.client.post(path, json=body, headers=h.cmd(uid, key))
    assert r.status_code == status, r.text
    return r.json()


async def get(h: Harness, path: str, uid: str, status: int = 200) -> Any:
    r = await h.client.get(path, headers=h.auth(uid))
    assert r.status_code == status, r.text
    return r.json()


async def link(h: Harness, student: str = ALEX, parent: str = PARENT_A) -> dict[str, Any]:
    created = await post(h, "/api/parent-links", student, {"scopes": ["summary:read"]}, 201)
    assert created["status"] == "pending" and created["inviteCode"]
    await post(h, "/api/parent/links/accept", parent, {"inviteCode": created["inviteCode"]}, 200)
    return dict(created)


async def test_invite_accept_and_summary(h: Harness) -> None:
    created = await link(h)
    links = (await get(h, "/api/parent-links", ALEX))["links"]
    assert [(x["linkId"], x["status"]) for x in links] == [(created["linkId"], "active")]
    assert links[0]["parentDisplayName"] == "Alex's parent (synthetic)"
    # The invite code is stored only as a hash.
    raw = h.store.raw(f"students/{ALEX}/parentLinks/{created['linkId']}")
    assert created["inviteCode"] not in json.dumps(raw, default=str)

    students = (await get(h, "/api/parent/students", PARENT_A))["students"]
    assert [s["studentId"] for s in students] == [ALEX]
    summary = await get(h, f"/api/parent/students/{ALEX}/summary", PARENT_A)
    assert summary["displayName"] == "Alex" and summary["grade"] == 11
    assert {c["courseId"] for c in summary["courses"]} == {"calc_bc", "dsat"}
    assert all(c["prediction"] == "unavailable" for c in summary["courses"])
    assert summary["week"]["planned"] >= 1


async def test_summary_is_a_projection_without_private_fields(h: Harness) -> None:
    await link(h)
    # Give Alex private material: a chat message and a submitted answer.
    r = await h.client.post(
        "/api/sessions", json={"taskId": "task_alex_calc_01"}, headers=h.cmd(ALEX)
    )
    sid = r.json()["sessionId"]
    secret = "MY PRIVATE ANSWER 3x^2 cos(x^3+1)"
    await h.client.post(f"/api/sessions/{sid}/messages", json={"text": secret}, headers=h.cmd(ALEX))
    summary = await get(h, f"/api/parent/students/{ALEX}/summary", PARENT_A)
    text = json.dumps(summary)
    assert secret not in text

    def keys(node: Any) -> set[str]:
        if isinstance(node, dict):
            return set(node) | set().union(*(keys(v) for v in node.values()))
        if isinstance(node, list):
            return set().union(*(keys(v) for v in node)) if node else set()
        return set()

    assert not keys(summary) & set(FORBIDDEN_KEYS)


async def test_parent_isolation(h: Harness) -> None:
    await link(h, ALEX, PARENT_A)
    await link(h, BETH, PARENT_B)
    # Parent A cannot read Beth, and parent B cannot read Alex: both look nonexistent.
    await get(h, f"/api/parent/students/{BETH}/summary", PARENT_A, 404)
    await get(h, f"/api/parent/students/{ALEX}/summary", PARENT_B, 404)
    await get(h, "/api/parent/students/stu_nobody/summary", PARENT_A, 404)
    linked = (await get(h, "/api/parent/students", PARENT_B))["students"]
    assert [s["studentId"] for s in linked] == [BETH]


async def test_roles_do_not_mix(h: Harness) -> None:
    await get(h, f"/api/parent/students/{ALEX}/summary", ALEX, 403)  # a student is not a parent
    await get(h, "/api/parent/students", "author_hsos", 403)
    await get(h, "/api/twin", PARENT_A, 403)  # a parent has no student record
    await get(h, "/api/parent-links", PARENT_A, 403)


async def test_revocation_is_checked_on_every_access(h: Harness) -> None:
    created = await link(h)
    await get(h, f"/api/parent/students/{ALEX}/summary", PARENT_A)
    revoked = await post(h, f"/api/parent-links/{created['linkId']}/revoke", ALEX, {}, 200)
    assert revoked["status"] == "revoked" and revoked["revokedAt"]
    await get(h, f"/api/parent/students/{ALEX}/summary", PARENT_A, 404)
    assert (await get(h, "/api/parent/students", PARENT_A))["students"] == []
    # Even a stale index entry the revoke missed would not grant access: the student-side
    # link is the authority.
    h.put_doc(
        f"parents/{PARENT_A}/children/{ALEX}",
        {"studentId": ALEX, "linkId": created["linkId"], "createdAt": h.clock.now()},
    )
    await get(h, f"/api/parent/students/{ALEX}/summary", PARENT_A, 404)


async def test_invite_codes_are_single_use_and_expire(h: Harness) -> None:
    created = await post(h, "/api/parent-links", ALEX, {"scopes": ["summary:read"]}, 201)
    code = created["inviteCode"]
    await post(h, "/api/parent/links/accept", PARENT_A, {"inviteCode": code}, 200)
    await post(h, "/api/parent/links/accept", PARENT_B, {"inviteCode": code}, 404)  # used
    await post(h, "/api/parent/links/accept", PARENT_B, {"inviteCode": "WRONGCODE"}, 404)

    late = await post(h, "/api/parent-links", ALEX, {"scopes": ["summary:read"]}, 201)
    h.clock.advance(days=8)
    await post(h, "/api/parent/links/accept", PARENT_B, {"inviteCode": late["inviteCode"]}, 404)
    links = (await get(h, "/api/parent-links", ALEX))["links"]
    statuses = {x["linkId"]: x["status"] for x in links}
    assert statuses[late["linkId"]] == "expired"


async def test_parent_link_commands_are_idempotent(h: Harness) -> None:
    key = idem()
    first = await post(h, "/api/parent-links", ALEX, {"scopes": ["summary:read"]}, 201, key)
    again = await post(h, "/api/parent-links", ALEX, {"scopes": ["summary:read"]}, 201, key)
    assert again["linkId"] == first["linkId"] and again["inviteCode"] is None  # shown once
    accept_key = idem()
    body = {"inviteCode": first["inviteCode"]}
    one = await post(h, "/api/parent/links/accept", PARENT_A, body, 200, accept_key)
    two = await post(h, "/api/parent/links/accept", PARENT_A, body, 200, accept_key)
    assert one["studentId"] == two["studentId"] == ALEX
    await post(h, "/api/parent/links/accept", PARENT_A, {"inviteCode": "OTHER"}, 409, accept_key)


async def test_only_summary_scope_can_be_granted(h: Harness) -> None:
    r = await h.client.post(
        "/api/parent-links", json={"scopes": ["learning:read"]}, headers=h.cmd(ALEX)
    )
    assert r.status_code == 400


async def test_deleting_a_student_removes_parent_access(h: Harness) -> None:
    from app.adapters.firestore.backup import delete_student

    created = await link(h)
    pending = await post(h, "/api/parent-links", ALEX, {"scopes": ["summary:read"]}, 201)
    assert h.store.paths(f"parents/{PARENT_A}/children/") != []
    await delete_student(h.store, ALEX, now=h.clock.now())
    assert h.store.paths(f"parents/{PARENT_A}/children/") == []
    invites = [h.store.raw(p) for p in h.store.paths("parentInvites/")]
    assert all(i["studentId"] != ALEX for i in invites)
    assert created["linkId"] and pending["linkId"]
    await get(h, f"/api/parent/students/{ALEX}/summary", PARENT_A, 404)
