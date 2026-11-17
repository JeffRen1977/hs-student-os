"""Step 40: the authoring assistant — turns, typed proposals, accept/reject (synthetic data).

The model is a scripted provider. Proposals change nothing until a person accepts them;
accepting runs the normal bank/selection commands as that person; stale edits are refused;
keys accepted by an author stay `agent-suggested`; design mode is for the content reviewer.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.support import Harness, ScriptedProvider, build_harness

AUTHOR, REVIEWER, OTHER, STUDENT = "author_hsos", "reviewer_hsos", "author_sample", "stu_alex"
TURNS, ITEMS, BATCH = "/api/bank/assistant/turns", "/api/bank/items", "/api/bank/imports/batch"
SKILL = "dsat.algebra.linear-equations"
MC = {"type": "mc", "choices": {"A": "1", "B": "2", "C": "3", "D": "4"}}


def make(
    clean_env: pytest.MonkeyPatch, *replies: Any, **settings: Any
) -> tuple[Harness, ScriptedProvider]:
    provider = ScriptedProvider(*replies)
    return build_harness(clean_env, llm_provider=provider, **settings), provider  # type: ignore[arg-type]


async def call(h: Harness, method: str, path: str, uid: str, status: int, body: Any = None) -> Any:
    if method == "GET":
        r = await h.client.get(path, headers=h.auth(uid))
    else:
        r = await h.client.request(method, path, json=body or {}, headers=h.cmd(uid))
    assert r.status_code == status, r.text
    return r.json()


async def drafts(h: Harness, *stems: str) -> list[str]:
    body = {
        "questions": [{"number": n + 1, "content": {"stem": s, **MC}} for n, s in enumerate(stems)],
        "settings": {"courseId": "dsat"},
    }
    return list((await call(h, "POST", BATCH, AUTHOR, 201, body))["itemIds"])


async def turn(h: Harness, uid: str, body: dict[str, Any]) -> dict[str, Any]:
    t = await call(h, "POST", TURNS, uid, 202, body)
    assert t["status"] == "QUEUED"
    await h.services.assistant_processor.process_due()
    return await call(h, "GET", f"{TURNS}/{t['turnId']}", uid, 200)  # type: ignore[no-any-return]


def bank_reply(a: str, b: str) -> dict[str, Any]:
    return {
        "reply": "I fixed a typo, suggested a key, and drafted one more question.",
        "proposals": [
            {
                "kind": "edit-item",
                "summary": "Fix typo",
                "itemId": a,
                "changes": {"stem": "What is 1 + 1?"},
            },
            {
                "kind": "propose-key",
                "summary": "Key B",
                "itemId": a,
                "answer": "b",
                "solution": "1 + 1 = 2.",
            },
            {
                "kind": "flag",
                "summary": "Check source",
                "itemId": b,
                "flag": "needs-source-check",
                "note": "?",
            },
            {
                "kind": "create-item",
                "summary": "New question",
                "question": {
                    "stem": "What is 2 + 2?",
                    "choices": {"A": "3", "B": "4", "C": "5", "D": "6"},
                    "answer": "B",
                    "solution": "Add.",
                    "skillIds": [SKILL],
                    "drafted": True,
                },
                "passage": {"title": "Numbers", "text": "A short passage about adding."},
            },
            {
                "kind": "link-passage",
                "summary": "Shared passage",
                "itemIds": [a, b],
                "passage": {"title": "Questions 1-2", "text": "A passage for both."},
            },
        ],
    }


async def test_proposals_change_nothing_until_accepted(clean_env: pytest.MonkeyPatch) -> None:
    h, provider = make(clean_env)
    a, b = await drafts(h, "What is 1 + 1 ?", "Second question")
    provider.queue(bank_reply(a, b))
    t = await turn(
        h, AUTHOR, {"message": "Fix the first item and suggest a key.", "itemIds": [a, b]}
    )
    assert t["status"] == "SUCCEEDED" and t["reply"].startswith("I fixed")
    assert [p["kind"] for p in t["proposals"]] == [
        "edit-item",
        "propose-key",
        "flag",
        "create-item",
        "link-passage",
    ]
    assert t["proposals"][0]["payload"]["basedOnRevision"] == 1  # from the snapshot
    prompt = provider.calls[0]["messages"][0].text
    assert (
        "<request>\nFix the first item" in prompt
        and "What is 1 + 1 ?" in prompt.split("<request>")[0]
    )
    assert (await call(h, "GET", f"{ITEMS}/{a}", AUTHOR, 200))["current"][
        "stem"
    ] == "What is 1 + 1 ?"

    tid = t["turnId"]
    done = await call(h, "POST", f"{TURNS}/{tid}/proposals/0/accept", AUTHOR, 200)
    assert done["proposals"][0]["status"] == "accepted"
    item = await call(h, "GET", f"{ITEMS}/{a}", AUTHOR, 200)
    assert item["current"]["stem"] == "What is 1 + 1?" and item["revision"] == 2

    # the key proposal is now stale (the edit bumped the revision): refused, nothing written
    err = await call(h, "POST", f"{TURNS}/{tid}/proposals/1/accept", AUTHOR, 409)
    assert err["error"]["code"] == "VERSION_CONFLICT"
    await call(h, "POST", f"{TURNS}/{tid}/proposals/1/reject", AUTHOR, 200)
    await call(
        h, "POST", f"{TURNS}/{tid}/proposals/1/accept", AUTHOR, 409
    )  # rejected stays rejected

    await call(h, "POST", f"{TURNS}/{tid}/proposals/2/accept", AUTHOR, 200)
    assert (
        "needs-source-check"
        in (await call(h, "GET", f"{ITEMS}/{b}", AUTHOR, 200))["current"]["flags"]
    )

    created = await call(h, "POST", f"{TURNS}/{tid}/proposals/3/accept", AUTHOR, 200)
    again = await call(h, "POST", f"{TURNS}/{tid}/proposals/3/accept", AUTHOR, 200)  # no-op
    new_id = created["proposals"][3]["result"]
    assert again["proposals"][3]["result"] == new_id
    new = await call(h, "GET", f"{ITEMS}/{new_id}", AUTHOR, 200)
    assert new["state"] == "extracted" and new["current"]["provenance"]["kind"] == "agent-drafted"
    assert new["current"]["answerSource"] == "agent-suggested" and new["current"]["passageId"]
    assert "agent-drafted" in new["current"]["flags"]


async def test_keys_accepted_by_an_author_stay_suggestions(clean_env: pytest.MonkeyPatch) -> None:
    h, provider = make(clean_env)
    (a,) = await drafts(h, "Key me")
    key = {
        "kind": "propose-key",
        "summary": "Key C",
        "itemId": a,
        "answer": "C",
        "solution": "Because.",
    }
    provider.queue({"reply": "ok", "proposals": [key]}, {"reply": "ok", "proposals": [key]})
    t = await turn(h, AUTHOR, {"message": "Key?", "itemIds": [a]})
    await call(h, "POST", f"{TURNS}/{t['turnId']}/proposals/0/accept", AUTHOR, 200)
    cur = (await call(h, "GET", f"{ITEMS}/{a}", AUTHOR, 200))["current"]
    assert (cur["answer"], cur["answerSource"]) == ("C", "agent-suggested")
    await call(h, "POST", f"{ITEMS}/{a}/submit", AUTHOR, 200)
    r = await turn(h, REVIEWER, {"message": "Key?", "itemIds": [a]})  # the content reviewer asks
    await call(h, "POST", f"{TURNS}/{r['turnId']}/proposals/0/accept", REVIEWER, 200)
    cur = (await call(h, "GET", f"{ITEMS}/{a}", REVIEWER, 200))["current"]
    assert (cur["answer"], cur["answerSource"]) == ("C", "reviewer")


async def test_reviewer_cannot_accept_a_key_for_a_changed_item(
    clean_env: pytest.MonkeyPatch,
) -> None:
    h, provider = make(clean_env)
    (iid,) = await drafts(h, "What is 2 + 2?")
    provider.queue(
        {
            "reply": "Use B.",
            "proposals": [
                {
                    "kind": "propose-key",
                    "summary": "Key B",
                    "itemId": iid,
                    "answer": "B",
                    "solution": "Two plus two is four.",
                }
            ],
        }
    )
    t = await turn(h, REVIEWER, {"message": "Check the key", "itemIds": [iid]})
    await call(
        h,
        "PATCH",
        f"{ITEMS}/{iid}",
        AUTHOR,
        200,
        {
            "expectedRevision": 1,
            "changes": {"stem": "What is 3 + 3?"},
        },
    )
    err = await call(h, "POST", f"{TURNS}/{t['turnId']}/proposals/0/accept", REVIEWER, 409)
    assert err["error"]["code"] == "VERSION_CONFLICT"
    current = await call(h, "GET", f"{ITEMS}/{iid}", REVIEWER, 200)
    assert current["current"]["answer"] is None
    assert current["current"]["stem"] == "What is 3 + 3?"


async def test_turns_are_private_to_whoever_asked(clean_env: pytest.MonkeyPatch) -> None:
    h, provider = make(clean_env)
    provider.queue({"reply": "Nothing to change.", "proposals": []})
    t = await turn(h, AUTHOR, {"message": "Hello"})
    for uid in (REVIEWER, OTHER):
        await call(h, "GET", f"{TURNS}/{t['turnId']}", uid, 404)
    await call(h, "GET", TURNS, STUDENT, 403)
    assert [x["turnId"] for x in (await call(h, "GET", TURNS, AUTHOR, 200))["turns"]] == [
        t["turnId"]
    ]
    (a,) = await drafts(h, "Mine")
    await call(h, "POST", TURNS, OTHER, 404, {"message": "Edit theirs", "itemIds": [a]})


async def test_proposals_about_unselected_items_are_rejected(clean_env: pytest.MonkeyPatch) -> None:
    h, provider = make(clean_env)
    (a,) = await drafts(h, "Selected")
    bad = {
        "reply": "x",
        "proposals": [
            {"kind": "edit-item", "summary": "s", "itemId": "bki_nope", "changes": {"stem": "y"}}
        ],
    }
    provider.queue(bad, bad, bad)  # every attempt invalid
    t = await turn(h, AUTHOR, {"message": "Edit", "itemIds": [a]})
    assert t["status"] == "FAILED" and t["error"].startswith(
        "The assistant's answer could not be used"
    )
    assert t["proposals"] == []


async def test_budget_and_missing_model_are_reported(clean_env: pytest.MonkeyPatch) -> None:
    h, provider = make(clean_env, org_job_token_budget=1_000)
    t = await turn(h, AUTHOR, {"message": "Hello"})
    assert t["status"] == "FAILED" and "budget for authoring is used up" in t["error"]
    assert provider.calls == []
    plain = build_harness(clean_env)  # mock provider: no model
    r = await plain.client.post(TURNS, json={"message": "Hello"}, headers=plain.cmd(AUTHOR))
    assert r.status_code == 400 and "needs a model" in r.json()["error"]["message"]


async def test_design_mode_builds_a_selection_with_added_skills(
    clean_env: pytest.MonkeyPatch,
) -> None:
    h, provider = make(clean_env)
    ids = await drafts(h, "Algebra one?", "Algebra two?", "Geometry one?")
    for iid in ids:
        item = await call(h, "GET", f"{ITEMS}/{iid}", AUTHOR, 200)
        await call(
            h,
            "PATCH",
            f"{ITEMS}/{iid}",
            AUTHOR,
            200,
            {
                "expectedRevision": item["revision"],
                "changes": {"answer": "A", "answerSource": "source-key"},
            },
        )
        await call(h, "POST", f"{ITEMS}/{iid}/submit", AUTHOR, 200)
        await call(h, "POST", f"{ITEMS}/{iid}/approve", REVIEWER, 200)
    geo = "dsat.geometry.circles-test"
    provider.queue(
        {
            "reply": "Two sets; geometry needs a new skill.",
            "proposals": [
                {
                    "kind": "selection-sets",
                    "summary": "Two sets",
                    "name": "Assistant plan",
                    "sets": [
                        {
                            "setId": "algebra-1",
                            "title": "Algebra",
                            "taskTitle": "Algebra practice",
                            "itemIds": ids[:2],
                            "skillIds": [SKILL],
                            "role": "starter",
                        },
                        {
                            "setId": "geometry-1",
                            "title": "Geometry",
                            "taskTitle": "Geometry practice",
                            "itemIds": ids[2:],
                            "skillIds": [geo],
                            "role": "sequence",
                        },
                    ],
                },
                {
                    "kind": "add-skill",
                    "summary": "Add circles",
                    "skill": {"skillId": geo, "name": "Circles"},
                },
                {
                    "kind": "edit-item",
                    "summary": "Tag",
                    "itemId": ids[2],
                    "changes": {"skillIds": [geo]},
                },
            ],
        }
    )
    await call(
        h, "POST", TURNS, AUTHOR, 403, {"message": "Plan", "mode": "design", "courseId": "dsat"}
    )
    t = await turn(h, REVIEWER, {"message": "Plan sets", "mode": "design", "courseId": "dsat"})
    assert t["status"] == "SUCCEEDED", t
    tid = t["turnId"]
    err = await call(h, "POST", f"{TURNS}/{tid}/proposals/1/accept", REVIEWER, 400)
    assert "Accept the proposed sets first" in err["error"]["message"]
    sets = await call(h, "POST", f"{TURNS}/{tid}/proposals/0/accept", REVIEWER, 200)
    sid = sets["proposals"][0]["result"]
    await call(h, "POST", f"{TURNS}/{tid}/proposals/1/accept", REVIEWER, 200)
    sel = await call(h, "GET", f"/api/bank/selections/{sid}", REVIEWER, 200)
    assert [s["setId"] for s in sel["sets"]] == ["algebra-1", "geometry-1"]
    assert sel["starterSetIds"] == ["algebra-1"] and sel["addedSkills"][0]["skillId"] == geo
    built = await call(
        h, "POST", f"/api/bank/selections/{sid}/build", REVIEWER, 201, {"version": "9.2.0"}
    )
    assert built["package"]["report"]["valid"], built["package"]["report"]
    full = await call(h, "GET", "/api/authoring/packages/dsat/versions/9.2.0", REVIEWER, 200)
    assert geo in {k["skillId"] for k in full["package"]["skills"]}
