"""Step 39A: quick entry into the question bank — preview, batch import, duplicates.

Synthetic questions only. Preview never writes; a batch is one transaction recorded as an
import job; duplicates (same content hash in the organization or in the batch) are skipped
unless kept.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.support import Harness, build_harness

AUTHOR, REVIEWER, OTHER = "author_hsos", "reviewer_hsos", "author_sample"
PLATFORM_REVIEWER, STUDENT = "reviewer_platform", "stu_alex"
PARSE, BATCH, IMPORTS, ITEMS = (
    "/api/bank/imports/parse",
    "/api/bank/imports/batch",
    "/api/bank/imports",
    "/api/bank/items",
)

PASTE = """Questions 1-2 refer to the following passage.
A synthetic passage about tide pools.

1. What does the passage describe?
A) storms
B) tide pools
C) ships
D) rivers
2. What lives there?
A) small animals B) trains C) clouds D) stars
3. What is 2 + 2?
A) 3
B) 4
C) 5
D) 6

Answers
1. B 2. A 3. B
"""


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch) -> Harness:
    return build_harness(clean_env)


async def call(h: Harness, method: str, path: str, uid: str, status: int, body: Any = None) -> Any:
    if method == "GET":
        r = await h.client.get(path, headers=h.auth(uid))
    elif path == PARSE:
        r = await h.client.post(path, json=body, headers=h.auth(uid))  # no Idempotency-Key needed
    else:
        r = await h.client.request(method, path, json=body or {}, headers=h.cmd(uid))
    assert r.status_code == status, r.text
    return r.json()


def batch_from(preview: dict[str, Any], **settings: Any) -> dict[str, Any]:
    return {
        "questions": [
            {
                "number": q["number"],
                "passageRef": q["passageRef"],
                "content": {k: v for k, v in q["content"].items() if v is not None},
            }
            for q in preview["questions"]
        ],
        "passages": [
            {"ref": p["ref"], "title": p["title"], "text": p["text"]} for p in preview["passages"]
        ],
        "settings": settings,
    }


async def items(h: Harness, uid: str = AUTHOR) -> list[dict[str, Any]]:
    out = []
    for s in (await call(h, "GET", f"{ITEMS}?limit=200", uid, 200))["items"]:
        out.append(await call(h, "GET", f"{ITEMS}/{s['itemId']}", uid, 200))
    return out


async def test_preview_splits_and_writes_nothing(h: Harness) -> None:
    preview = await call(h, "POST", PARSE, AUTHOR, 200, {"format": "text", "text": PASTE})
    assert [q["number"] for q in preview["questions"]] == [1, 2, 3]
    assert [q["content"]["answer"] for q in preview["questions"]] == ["B", "A", "B"]
    assert preview["passages"][0]["rangeFrom"] == 1 and preview["passages"][0]["rangeTo"] == 2
    assert all(q["problems"] == [] and q["duplicateOf"] is None for q in preview["questions"])
    assert await items(h) == []
    await call(h, "POST", PARSE, STUDENT, 403, {"text": PASTE})
    await call(h, "POST", PARSE, PLATFORM_REVIEWER, 403, {"text": PASTE})


async def test_batch_creates_drafts_with_settings_passages_and_a_job(h: Harness) -> None:
    preview = await call(h, "POST", PARSE, AUTHOR, 200, {"text": PASTE})
    body = batch_from(
        preview,
        courseId="dsat",
        section="reading",
        skillIds=["dsat.information-ideas.central-ideas"],
        difficulty="easy",
        keyOrigin="compiled-key",
        sourceTitle="Synthetic worksheet",
        tags=["paste"],
    )
    job = await call(h, "POST", BATCH, AUTHOR, 201, body)
    assert job["kind"] == "batch" and job["status"] == "SUCCEEDED" and job["itemCount"] == 3
    assert len(job["passageIds"]) == 1 and job["skipped"] == []
    rows = {i["current"]["provenance"]["region"]: i for i in await items(h)}
    q1 = rows["question 1"]
    assert q1["state"] == "draft" and q1["courseId"] == "dsat" and q1["tags"] == ["paste"]
    cur = q1["current"]
    assert (cur["section"], cur["difficulty"], cur["answer"], cur["answerSource"]) == (
        "reading",
        "easy",
        "B",
        "compiled-key",
    )
    assert cur["passageId"] == job["passageIds"][0] == rows["question 2"]["current"]["passageId"]
    assert rows["question 3"]["current"]["passageId"] is None
    assert cur["provenance"]["importJobId"] == job["jobId"]
    assert cur["provenance"]["reference"] == "Synthetic worksheet"
    listed = await call(h, "GET", IMPORTS, AUTHOR, 200)
    assert [j["jobId"] for j in listed["imports"]] == [job["jobId"]]
    await call(h, "GET", f"{IMPORTS}/{job['jobId']}", OTHER, 404)


async def test_batch_is_idempotent_and_conflicting_reuse_is_rejected(h: Harness) -> None:
    body = batch_from(await call(h, "POST", PARSE, AUTHOR, 200, {"text": PASTE}))
    headers = h.cmd(AUTHOR)
    a = await h.client.post(BATCH, json=body, headers=headers)
    b = await h.client.post(BATCH, json=body, headers=headers)
    assert a.status_code == b.status_code == 201 and b.headers.get("Idempotency-Replayed") == "true"
    assert a.json()["jobId"] == b.json()["jobId"] and len(await items(h)) == 3
    c = await h.client.post(BATCH, json={**body, "keepDuplicates": True}, headers=headers)
    assert c.status_code == 409 and c.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_duplicates_are_marked_and_skipped_unless_kept(h: Harness) -> None:
    body = batch_from(await call(h, "POST", PARSE, AUTHOR, 200, {"text": PASTE}))
    await call(h, "POST", BATCH, AUTHOR, 201, body)
    again = await call(h, "POST", PARSE, REVIEWER, 200, {"text": PASTE})  # same organization
    assert all(q["duplicateOf"] and q["duplicateOf"].startswith("bki_") for q in again["questions"])
    other = await call(h, "POST", PARSE, OTHER, 200, {"text": PASTE})  # another organization
    assert all(q["duplicateOf"] is None for q in other["questions"])

    job = await call(h, "POST", BATCH, AUTHOR, 201, body)
    assert (
        job["itemCount"] == 0
        and len(job["skipped"]) == 3
        and "duplicate of bki_" in job["skipped"][0]
    )
    kept = await call(h, "POST", BATCH, AUTHOR, 201, {**body, "keepDuplicates": True})
    assert kept["itemCount"] == 3
    flagged = await call(h, "GET", f"{ITEMS}/{kept['itemIds'][0]}", AUTHOR, 200)
    assert any(f.startswith("duplicate-of:bki_") for f in flagged["current"]["flags"])

    twice = await call(
        h,
        "POST",
        PARSE,
        AUTHOR,
        200,
        {"text": "1. New?\nA) a\nB) b\nC) c\nD) d\n2. New?\nA) a\nB) b\nC) c\nD) d\n"},
    )
    assert twice["questions"][1]["duplicateOf"] == "question 1"


async def test_an_invalid_batch_writes_nothing(h: Harness) -> None:
    good = {
        "number": 1,
        "content": {
            "stem": "Fine?",
            "choices": {"A": "a", "B": "b", "C": "c", "D": "d"},
            "answer": "A",
        },
    }
    bad = [
        {"number": 2, "passageRef": "p9", "content": {"stem": "Where is my passage?"}},
        {
            "number": 3,
            "content": {
                "stem": "Key?",
                "choices": {"A": "a", "B": "b", "C": "c", "D": "d"},
                "answer": "B",
                "answerSource": "reviewer",
            },
        },
    ]
    err = await call(h, "POST", BATCH, AUTHOR, 400, {"questions": [good, *bad]})
    message = err["error"]["message"]
    assert "passage “p9” is not in the batch" in message
    assert "only the content reviewer records reviewer keys" in message
    assert await items(h) == []


async def test_unkeyed_and_incomplete_questions_arrive_flagged(h: Harness) -> None:
    body = {
        "questions": [
            {
                "number": 1,
                "content": {"stem": "No key", "choices": {"A": "a", "B": "b", "C": "c", "D": "d"}},
            },
            {
                "number": 2,
                "content": {"stem": "Two choices", "choices": {"A": "a", "B": "b"}, "answer": "A"},
            },
        ]
    }
    job = await call(h, "POST", BATCH, AUTHOR, 201, body)
    flags = [
        (await call(h, "GET", f"{ITEMS}/{i}", AUTHOR, 200))["current"]["flags"]
        for i in job["itemIds"]
    ]
    assert "key-missing" in flags[0] and "choices-incomplete" in flags[1]


async def test_existing_passages_must_belong_to_the_organization(h: Harness) -> None:
    mc = {"stem": "Q?", "choices": {"A": "a", "B": "b", "C": "c", "D": "d"}, "answer": "A"}
    first = await call(
        h, "POST", BATCH, AUTHOR, 201,
        {"questions": [{"number": 1, "passageRef": "p1", "content": mc}],
         "passages": [{"ref": "p1", "title": "T", "text": "A synthetic passage."}]},
    )  # fmt: skip
    pid = first["passageIds"][0]
    same = {**mc, "stem": "Next?", "passageId": pid}
    second = await call(
        h, "POST", BATCH, AUTHOR, 201, {"questions": [{"number": 2, "content": same}]}
    )
    item = await call(h, "GET", f"{ITEMS}/{second['itemIds'][0]}", AUTHOR, 200)
    assert item["current"]["passageId"] == pid
    err = await call(h, "POST", BATCH, OTHER, 400, {"questions": [{"number": 1, "content": same}]})
    assert "is not in your organization's bank" in err["error"]["message"]
