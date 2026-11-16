"""Step 45.2: the question bank on real Firestore — item + version + history commit together,
concurrent edits resolve to exactly one winner, array-contains flag filtering, and another
organization cannot read the item."""

from __future__ import annotations

import asyncio
import secrets
from typing import Any

import pytest

from tests.emulator.test_firestore_flows import make_env
from tests.support import emulator_token, idem

ITEMS = "/api/bank/items"
ORG = "org_hsos_content"
MC = {
    "stem": "If 2x + 4 = 100, what is the value of 6x + 12?",
    "type": "mc",
    "choices": {"A": "400", "B": "300", "C": "288", "D": "48"},
}


@pytest.fixture
async def env() -> Any:
    return await make_env()


def headers(env: dict[str, Any], uid: str, key: str | None = None) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {emulator_token(uid, now=env['clock'].now())}",
        "Idempotency-Key": key or idem(),
    }


async def create(env: dict[str, Any], flag: str, **content: Any) -> dict[str, Any]:
    r = await env["http"].post(
        ITEMS,
        json={"content": {**MC, "flags": [flag], **content}},
        headers=headers(env, "author_hsos"),
    )
    assert r.status_code == 201, r.text
    return dict(r.json())


async def test_review_workflow_commits_header_versions_and_history(env: dict[str, Any]) -> None:
    flag = "run-" + secrets.token_hex(4)
    item = await create(env, flag, answer="B", answerSource="source-key")
    iid, http = item["itemId"], env["http"]
    for uid, action in (("author_hsos", "submit"), ("reviewer_hsos", "approve")):
        r = await http.post(f"{ITEMS}/{iid}/{action}", json={}, headers=headers(env, uid))
        assert r.status_code == 200, r.text
    header = (await env["db"].document(f"orgs/{ORG}/bankItems/{iid}").get()).to_dict()
    v1 = (await env["db"].document(f"orgs/{ORG}/bankItems/{iid}/versions/000001").get()).to_dict()
    assert header["state"] == "approved" and header["approvedVersion"] == 1
    assert [h["action"] for h in header["history"]] == ["create", "submit", "approve"]
    assert v1["submittedBy"] == "author_hsos" and v1["review"]["reviewerId"] == "reviewer_hsos"
    # a revision opens version 2 without touching version 1
    r = await http.patch(
        f"{ITEMS}/{iid}",
        json={"expectedRevision": header["revision"], "changes": {"stem": "Find 6x + 12."}},
        headers=headers(env, "author_hsos"),
    )
    assert r.status_code == 200 and r.json()["currentVersion"] == 2, r.text
    again = await env["db"].document(f"orgs/{ORG}/bankItems/{iid}/versions/000001").get()
    assert again.to_dict()["content"]["stem"] == MC["stem"]


async def test_concurrent_edits_have_exactly_one_winner(env: dict[str, Any]) -> None:
    item = await create(env, "run-" + secrets.token_hex(4))
    path = f"{ITEMS}/{item['itemId']}"
    bodies = [{"expectedRevision": 1, "changes": {"stem": f"Version {n}"}} for n in ("one", "two")]
    a, b = await asyncio.gather(
        *(
            env["http"].patch(path, json=body, headers=headers(env, "author_hsos"))
            for body in bodies
        )
    )
    assert sorted((a.status_code, b.status_code)) == [200, 409], (a.text, b.text)
    loser = a if a.status_code == 409 else b
    assert loser.json()["error"]["code"] == "VERSION_CONFLICT"
    final = (await env["http"].get(path, headers=headers(env, "author_hsos"))).json()
    assert final["revision"] == 2 and final["current"]["stem"] in ("Version one", "Version two")


async def test_flag_filter_and_organization_isolation(env: dict[str, Any]) -> None:
    flag = "run-" + secrets.token_hex(4)
    mine = [await create(env, flag) for _ in range(2)]
    await create(env, "run-" + secrets.token_hex(4))  # a different flag
    r = await env["http"].get(f"{ITEMS}?flag={flag}", headers=headers(env, "reviewer_hsos"))
    assert r.status_code == 200, r.text
    assert sorted(i["itemId"] for i in r.json()["items"]) == sorted(m["itemId"] for m in mine)
    other = await env["http"].get(
        f"{ITEMS}/{mine[0]['itemId']}", headers=headers(env, "author_sample")
    )
    assert other.status_code == 404


async def test_selection_and_build_on_real_firestore(env: dict[str, Any]) -> None:
    """Selection documents round-trip and a build uploads a valid draft package version."""
    http, flag = env["http"], "run-" + secrets.token_hex(4)
    ids = []
    for n in (1, 2):
        item = await create(
            env,
            flag,
            answer="B",
            answerSource="source-key",
            skillIds=["dsat.algebra.linear-equations"],
            stem=f"Item {n} {flag}",
        )
        for uid, action in (("author_hsos", "submit"), ("reviewer_hsos", "approve")):
            r = await http.post(
                f"{ITEMS}/{item['itemId']}/{action}", json={}, headers=headers(env, uid)
            )
            assert r.status_code == 200, r.text
        ids.append(item["itemId"])
    body = {
        "courseId": "dsat",
        "name": flag,
        "sets": [
            {
                "setId": "s1",
                "title": "Set 1",
                "taskTitle": "Practice",
                "items": [{"itemId": i} for i in ids],
            }
        ],
        "starterSetIds": ["s1"],
    }
    r = await http.post("/api/bank/selections", json=body, headers=headers(env, "reviewer_hsos"))
    assert r.status_code == 201, r.text
    sid = r.json()["selectionId"]
    stored = (await env["db"].document(f"orgs/{ORG}/selections/{sid}").get()).to_dict()
    assert [x["itemId"] for x in stored["sets"][0]["items"]] == ids
    version = f"{50 + secrets.randbelow(900)}.{secrets.randbelow(1000)}.0"
    r = await http.post(
        f"/api/bank/selections/{sid}/build",
        json={"version": version},
        headers=headers(env, "reviewer_hsos"),
    )
    assert r.status_code == 201, r.text
    assert r.json()["package"]["report"]["valid"] and r.json()["package"]["status"] == "draft"
    after = (await env["db"].document(f"orgs/{ORG}/selections/{sid}").get()).to_dict()
    assert after["builtPackageVersion"] == version and after["builtBy"] == "reviewer_hsos"


async def test_quick_entry_batch_and_duplicate_lookup_on_firestore(env: dict[str, Any]) -> None:
    """Step 39A: a batch commits items, passage and job together; the content-hash `in`
    query finds the duplicates on the next preview."""
    tag = secrets.token_hex(4)
    text = f"Questions 1-2 refer to the following passage.\nPassage {tag}.\n" + "".join(
        f"{n}. Question {tag} {n}?\nA) a\nB) b\nC) c\nD) d\nAnswer: A\n" for n in (1, 2, 3)
    )
    http = env["http"]
    r = await http.post(
        "/api/bank/imports/parse", json={"text": text}, headers=headers(env, "author_hsos")
    )
    preview = r.json()
    assert r.status_code == 200 and all(q["duplicateOf"] is None for q in preview["questions"])
    body = {
        "questions": [
            {"number": q["number"], "passageRef": q["passageRef"],
             "content": {k: v for k, v in q["content"].items() if v is not None}}
            for q in preview["questions"]
        ],
        "passages": [{"ref": p["ref"], "title": p["title"], "text": p["text"]}
                     for p in preview["passages"]],
    }  # fmt: skip
    r = await http.post("/api/bank/imports/batch", json=body, headers=headers(env, "author_hsos"))
    job = r.json()
    assert r.status_code == 201 and job["itemCount"] == 3, r.text
    stored = (await env["db"].document(f"orgs/{ORG}/imports/{job['jobId']}").get()).to_dict()
    assert stored["itemIds"] == job["itemIds"] and len(stored["passageIds"]) == 1
    r = await http.post(
        "/api/bank/imports/parse", json={"text": text}, headers=headers(env, "reviewer_hsos")
    )
    assert {q["duplicateOf"] for q in r.json()["questions"]} == set(job["itemIds"])
