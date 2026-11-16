"""Step 45.6: seeding a development organization's bank from a local bank file.

Uses synthetic records only (no real test content): passages and items keep their
provenance, flags and key origin; worked-out keys arrive as agent-suggested; re-running is
a replay; a changed record is reported, not duplicated; passages are org-scoped.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.domain.types.actor import ActorRole, PlatformActor
from scripts.seed_bank import seed_bank
from tests.support import Harness, build_harness

AUTHOR, REVIEWER, OTHER = "author_hsos", "reviewer_hsos", "author_sample"
ORG = "org_hsos_content"

PASSAGES = [
    {"passageId": "t1.reading-P1", "sourceId": "t1", "section": "reading", "page": 3,
     "title": "Questions 1-2 are based on the following passage.",
     "text": "A synthetic passage about tide pools and the animals that live in them.",
     "flags": ["vision-verified"]},
    {"passageId": "t1.reading-P9", "sourceId": "t1", "title": "unused", "text": "Not referenced."},
]  # fmt: skip
QUESTIONS: list[dict[str, Any]] = [
    {"id": "t1.reading.1", "sourceId": "t1", "sourceFile": "synthetic.pdf", "page": 4,
     "format": "paper-2016", "section": "reading", "number": 1, "passageId": "t1.reading-P1",
     "stem": "The passage mainly describes", "type": "mc",
     "choices": {"A": "tides", "B": "tide pools", "C": "fish", "D": "rocks"},
     "answer": "B", "answerSource": "official-key", "flags": ["vision-verified"],
     "status": "ready"},
    {"id": "t1.math-calc.31", "sourceId": "t1", "sourceFile": "synthetic.pdf", "page": 9,
     "section": "math-calc", "number": 31, "passageId": None,
     "stem": "What number is 10% greater than 50?", "type": "spr", "choices": None,
     "answer": "55", "answerSource": "solved", "flags": ["ocr"], "status": "needs-review"},
    {"id": "t1.reading.2", "sourceId": "t1", "sourceFile": "synthetic.pdf",
     "section": "reading", "number": 2, "passageId": "t1.reading-P1",
     "stem": "Garbled", "type": "mc", "choices": {"A": "x", "B": "y"},
     "answer": "29-34", "answerSource": "compiled-key", "compiledKey": "29-34",
     "flags": ["choices-incomplete"], "status": "needs-review"},
    {"id": "t1.writing.9", "sourceId": "t1", "section": "writing", "number": 9,
     "stem": "[[Nevertheless,]] the study continued.", "type": "mc",
     "choices": {"A": "NO CHANGE", "B": "At the same time,", "C": "On the other hand,",
                 "D": "DELETE the underlined portion."},
     "answer": "D", "answerSource": "solved", "compiledKey": "C",
     "flags": ["key-disputed", "vision-verified"], "status": "needs-review"},
    {"id": "t1.writing.10", "sourceId": "t1", "section": "writing", "number": 10,
     "stem": "No key here.", "type": "mc", "choices": None, "answer": None,
     "answerSource": None, "flags": ["key-missing"], "status": "no-key"},
]  # fmt: skip


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch) -> Harness:
    return build_harness(clean_env, seed_packages=False)


def author() -> PlatformActor:
    return PlatformActor.for_member(AUTHOR, ActorRole.AUTHOR, ORG)


async def items(h: Harness, uid: str = AUTHOR, query: str = "") -> list[dict[str, Any]]:
    r = await h.client.get(f"/api/bank/items?limit=200{query}", headers=h.auth(uid))
    assert r.status_code == 200, r.text
    out = []
    for summary in r.json()["items"]:
        d = await h.client.get(f"/api/bank/items/{summary['itemId']}", headers=h.auth(uid))
        out.append(d.json())
    return out


def by_region(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["current"]["provenance"]["region"]: r for r in rows}


async def test_seed_keeps_provenance_flags_and_key_origin(h: Harness) -> None:
    report = await seed_bank(h.services.bank, author(), QUESTIONS, PASSAGES)
    assert (report.passages_created, report.items_created, report.skipped) == (1, 5, [])
    rows = by_region(await items(h))
    assert set(rows) == {q["id"] for q in QUESTIONS}
    assert all(r["state"] == "extracted" for r in rows.values())

    first = rows["t1.reading.1"]
    cur = first["current"]
    assert cur["answer"] == "B" and cur["answerSource"] == "source-key"
    assert cur["provenance"] == {
        "kind": "imported", "sourceId": None, "page": 4, "region": "t1.reading.1",
        "importJobId": None, "reference": "synthetic.pdf",
    }  # fmt: skip
    assert "seed-status:ready" in cur["flags"] and first["tags"] == ["t1", "reading", "paper-2016"]
    passage = await h.client.get(f"/api/bank/passages/{cur['passageId']}", headers=h.auth(AUTHOR))
    assert passage.status_code == 200 and "tide pools" in passage.json()["text"]
    assert rows["t1.reading.2"]["current"]["passageId"] == cur["passageId"]  # shared passage

    spr = rows["t1.math-calc.31"]["current"]
    assert (spr["type"], spr["answer"], spr["answerSource"]) == ("spr", "55", "agent-suggested")
    # an mc answer that is not a choice letter is kept as a flag, not as a key
    bad = rows["t1.reading.2"]["current"]
    assert bad["answer"] is None and "seed-answer-not-a-choice:29-34" in bad["flags"]
    disputed = rows["t1.writing.9"]["current"]
    assert disputed["answerSource"] == "agent-suggested" and "compiled-key:C" in disputed["flags"]
    assert rows["t1.writing.10"]["current"]["answer"] is None


async def test_reseeding_replays_and_changed_records_are_reported(h: Harness) -> None:
    await seed_bank(h.services.bank, author(), QUESTIONS, PASSAGES)
    again = await seed_bank(h.services.bank, author(), QUESTIONS, PASSAGES)
    assert (again.items_created, again.items_replayed, again.passages_replayed) == (0, 5, 1)
    changed = [{**QUESTIONS[0], "stem": "Edited locally"}, *QUESTIONS[1:]]
    third = await seed_bank(h.services.bank, author(), changed, PASSAGES)
    assert third.items_created == 0 and [bid for bid, _ in third.skipped] == ["t1.reading.1"]
    assert len(await items(h)) == 5


async def test_verified_records_can_arrive_as_drafts_and_go_through_review(h: Harness) -> None:
    await seed_bank(
        h.services.bank, author(), QUESTIONS, PASSAGES, verified_as_draft=True, course_id="dsat"
    )
    rows = by_region(await items(h))
    assert rows["t1.reading.1"]["state"] == "draft"
    assert {r["courseId"] for r in rows.values()} == {"dsat"}  # selectable for the dsat package
    assert rows["t1.math-calc.31"]["state"] == "extracted"  # OCR only
    iid = rows["t1.reading.1"]["itemId"]
    for uid, action in ((AUTHOR, "submit"), (REVIEWER, "approve")):
        r = await h.client.post(f"/api/bank/items/{iid}/{action}", json={}, headers=h.cmd(uid))
        assert r.status_code == 200, r.text
    disputed = rows["t1.writing.9"]["itemId"]
    await h.client.post(f"/api/bank/items/{disputed}/submit", json={}, headers=h.cmd(AUTHOR))
    r = await h.client.post(f"/api/bank/items/{disputed}/approve", json={}, headers=h.cmd(REVIEWER))
    assert r.status_code == 409 and r.json()["error"]["code"] == "ITEM_KEY_REQUIRED"


async def test_passages_are_organization_scoped_and_must_exist(h: Harness) -> None:
    await seed_bank(h.services.bank, author(), QUESTIONS[:1], PASSAGES)
    pid = (await items(h))[0]["current"]["passageId"]
    other = await h.client.get(f"/api/bank/passages/{pid}", headers=h.auth(OTHER))
    assert other.status_code == 404
    body = {"content": {"stem": "s", "passageId": "bkp_nope"}}
    r = await h.client.post("/api/bank/items", json=body, headers=h.cmd(AUTHOR))
    assert r.status_code == 400 and "passageId" in r.json()["error"]["message"]
    # another organization cannot point its items at this organization's passage
    r = await h.client.post(
        "/api/bank/items", json={"content": {"stem": "s", "passageId": pid}}, headers=h.cmd(OTHER)
    )
    assert r.status_code == 400
