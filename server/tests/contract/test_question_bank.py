"""Step 45.2–45.3: the organization question bank and its content review.

Authors create, edit and submit items; the organization's content reviewer (who is also an
author and may review their own items) keys, approves, rejects and retires them. Other
organizations never see an item (404); students, platform reviewers and admins have no bank
(403). Every command is idempotent, edits use optimistic concurrency, and an approved
version never changes.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.domain.bank_service import CreateItemInput
from app.domain.commands import CommandKey
from app.domain.types.actor import ActorRole, PlatformActor
from app.domain.types.bank import BankItemState, ItemContent, ItemType
from tests.support import Harness, build_harness, idem

AUTHOR, REVIEWER = "author_hsos", "reviewer_hsos"  # org_hsos_content
OTHER_AUTHOR = "author_sample"  # org_sample_press
PLATFORM_REVIEWER, ADMIN, STUDENT = "reviewer_platform", "admin_platform", "stu_alex"
ITEMS = "/api/bank/items"

MC = {
    "section": "math-calc",
    "skillIds": ["dsat.algebra.linear-equations"],
    "difficulty": "easy",
    "stem": "If 3(c + d) = 5, what is the value of c + d?",
    "type": "mc",
    "choices": {"A": "3/5", "B": "5/3", "C": "3", "D": "5"},
}


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch) -> Harness:
    return build_harness(clean_env, seed_packages=False)


async def call(
    h: Harness,
    method: str,
    path: str,
    uid: str,
    status: int,
    body: dict[str, Any] | None = None,
    key: str | None = None,
) -> Any:
    if method == "GET":
        r = await h.client.get(path, headers=h.auth(uid))
    else:
        r = await h.client.request(method, path, json=body or {}, headers=h.cmd(uid, key))
    assert r.status_code == status, r.text
    return r.json()


async def create(h: Harness, uid: str = AUTHOR, **content: Any) -> dict[str, Any]:
    body = {"courseId": "dsat", "tags": ["og5"], "content": {**MC, **content}}
    return await call(h, "POST", ITEMS, uid, 201, body)


async def act(
    h: Harness, item_id: str, action: str, uid: str, status: int = 200, **body: Any
) -> Any:
    return await call(h, "POST", f"{ITEMS}/{item_id}/{action}", uid, status, body)


async def edit(
    h: Harness, item: dict[str, Any], uid: str, status: int = 200, **changes: Any
) -> Any:
    body = {"expectedRevision": item["revision"], "changes": changes}
    return await call(h, "PATCH", f"{ITEMS}/{item['itemId']}", uid, status, body)


def code(err: dict[str, Any]) -> str:
    return str(err["error"]["code"])


# ---- Creation, reading, isolation ------------------------------------------------------------


async def test_author_creates_a_draft_item_with_provenance(h: Harness) -> None:
    item = await create(h)
    assert item["state"] == "draft" and item["currentVersion"] == 1
    assert item["approvedVersion"] is None and item["revision"] == 1
    assert item["orgId"] == "org_hsos_content"
    cur = item["current"]
    assert cur["stem"].startswith("If 3(c + d)") and cur["choices"]["B"] == "5/3"
    assert cur["provenance"]["kind"] == "author" and cur["createdBy"] == AUTHOR
    got = await call(h, "GET", f"{ITEMS}/{item['itemId']}", AUTHOR, 200)
    assert [v["number"] for v in got["versions"]] == [1]
    listed = await call(h, "GET", ITEMS, REVIEWER, 200)  # same organization
    assert [i["itemId"] for i in listed["items"]] == [item["itemId"]]


async def test_other_organizations_never_see_an_item(h: Harness) -> None:
    item = await create(h)
    iid = item["itemId"]
    assert code(await call(h, "GET", f"{ITEMS}/{iid}", OTHER_AUTHOR, 404)) == "NOT_FOUND"
    assert (await call(h, "GET", ITEMS, OTHER_AUTHOR, 200))["items"] == []
    await act(h, iid, "submit", OTHER_AUTHOR, 404)
    await edit(h, item, OTHER_AUTHOR, 404, stem="changed")


@pytest.mark.parametrize("uid", [STUDENT, PLATFORM_REVIEWER, ADMIN])
async def test_students_platform_reviewers_and_admins_have_no_bank(h: Harness, uid: str) -> None:
    assert code(await call(h, "GET", ITEMS, uid, 403)) == "FORBIDDEN"
    err = await call(h, "POST", ITEMS, uid, 403, {"content": MC})
    assert code(err) == "FORBIDDEN"


async def test_authors_cannot_key_approve_reject_or_retire(h: Harness) -> None:
    item = await create(h, answer="B", answerSource="source-key")
    iid = item["itemId"]
    await act(h, iid, "submit", AUTHOR)
    await act(h, iid, "key", AUTHOR, 403, answer="B")
    await act(h, iid, "approve", AUTHOR, 403)
    await act(h, iid, "reject", AUTHOR, 403, notes="no")
    await act(h, iid, "retire", AUTHOR, 403, notes="no")


async def test_list_filters_by_state_and_flag_with_a_cursor(h: Harness) -> None:
    a = await create(h, flags=["figure-described"])
    b = await create(h)
    c = await create(h, flags=["figure-described"])
    await act(h, b["itemId"], "submit", AUTHOR)
    flagged = await call(h, "GET", f"{ITEMS}?flag=figure-described", AUTHOR, 200)
    assert [i["itemId"] for i in flagged["items"]] == [a["itemId"], c["itemId"]]
    review = await call(h, "GET", f"{ITEMS}?state=in_review", REVIEWER, 200)
    assert [i["itemId"] for i in review["items"]] == [b["itemId"]]
    page1 = await call(h, "GET", f"{ITEMS}?limit=2", AUTHOR, 200)
    assert len(page1["items"]) == 2 and page1["nextCursor"] == page1["items"][-1]["itemId"]
    page2 = await call(h, "GET", f"{ITEMS}?limit=2&cursor={page1['nextCursor']}", AUTHOR, 200)
    assert [i["itemId"] for i in page2["items"]] == [c["itemId"]] and page2["nextCursor"] is None


# ---- Idempotency and concurrency ---------------------------------------------------------------


async def test_create_replays_the_same_item_and_rejects_a_different_body(h: Harness) -> None:
    key = idem()
    body = {"content": MC}
    first = await h.client.post(ITEMS, json=body, headers=h.cmd(AUTHOR, key))
    again = await h.client.post(ITEMS, json=body, headers=h.cmd(AUTHOR, key))
    assert first.status_code == again.status_code == 201
    assert again.headers.get("Idempotency-Replayed") == "true"
    assert first.json()["itemId"] == again.json()["itemId"]
    other = await h.client.post(
        ITEMS, json={"content": {**MC, "stem": "x"}}, headers=h.cmd(AUTHOR, key)
    )
    assert other.status_code == 409 and code(other.json()) == "IDEMPOTENCY_CONFLICT"
    assert len((await call(h, "GET", ITEMS, AUTHOR, 200))["items"]) == 1


async def test_a_stale_revision_is_a_version_conflict(h: Harness) -> None:
    item = await create(h)
    updated = await edit(h, item, AUTHOR, stem="If 3(c + d) = 6, what is c + d?")
    assert updated["revision"] == 2 and updated["currentVersion"] == 1
    assert code(await edit(h, item, AUTHOR, 409, stem="late")) == "VERSION_CONFLICT"


# ---- Keys, review and the state machine ---------------------------------------------------


async def test_review_requires_a_confirmed_key_then_records_submitter_and_approver(
    h: Harness,
) -> None:
    item = await create(h)  # no key in the source
    iid = item["itemId"]
    submitted = await act(h, iid, "submit", AUTHOR)
    assert submitted["state"] == "in_review" and submitted["current"]["submittedBy"] == AUTHOR
    # authors cannot change an item in review; the content reviewer can
    assert code(await edit(h, submitted, AUTHOR, 409, stem="x")) == "INVALID_STATE_TRANSITION"
    assert code(await act(h, iid, "approve", REVIEWER, 409)) == "ITEM_KEY_REQUIRED"
    keyed = await act(h, iid, "key", REVIEWER, answer="B", solution="3(c+d)=5, so c+d=5/3.")
    assert keyed["current"]["answerSource"] == "reviewer" and keyed["state"] == "in_review"
    approved = await act(h, iid, "approve", REVIEWER, notes="Key checked.")
    assert approved["state"] == "approved" and approved["approvedVersion"] == 1
    review = approved["current"]["review"]
    assert review["reviewerId"] == REVIEWER and review["decision"] == "approved"
    assert approved["current"]["submittedBy"] == AUTHOR
    assert [c["action"] for c in approved["history"]] == ["create", "submit", "key", "approve"]


async def test_a_content_reviewer_may_approve_an_item_they_wrote(h: Harness) -> None:
    item = await create(h, REVIEWER)
    iid = item["itemId"]
    await act(h, iid, "submit", REVIEWER)
    await act(h, iid, "key", REVIEWER, answer="B")
    approved = await act(h, iid, "approve", REVIEWER)
    assert approved["current"]["submittedBy"] == approved["current"]["review"]["reviewerId"]


async def test_agent_suggested_keys_need_the_reviewer_and_authors_cannot_claim_reviewer(
    h: Harness,
) -> None:
    item = await create(h, answer="B", answerSource="agent-suggested")
    iid = item["itemId"]
    await act(h, iid, "submit", AUTHOR)
    err = await act(h, iid, "approve", REVIEWER, 409)
    assert code(err) == "ITEM_KEY_REQUIRED" and "suggestion" in err["error"]["message"]
    await act(h, iid, "key", REVIEWER, answer="B")  # confirms it
    assert (await act(h, iid, "approve", REVIEWER))["current"]["answerSource"] == "reviewer"
    err = await call(
        h,
        "POST",
        ITEMS,
        AUTHOR,
        403,
        {"content": {**MC, "answer": "B", "answerSource": "reviewer"}},
    )
    assert code(err) == "FORBIDDEN"


async def test_source_keys_are_approvable_and_incomplete_items_are_not(h: Harness) -> None:
    item = await create(h, answer="B", answerSource="source-key")
    await act(h, item["itemId"], "submit", AUTHOR)
    assert (await act(h, item["itemId"], "approve", REVIEWER))["state"] == "approved"
    partial = await create(h, choices={"A": "1", "B": "2"}, answer="A", answerSource="source-key")
    await act(h, partial["itemId"], "submit", AUTHOR)
    err = await act(h, partial["itemId"], "approve", REVIEWER, 400)
    assert code(err) == "VALIDATION_FAILED" and "choices A, B, C and D" in err["error"]["message"]


async def test_editing_an_approved_item_opens_a_new_version_and_keeps_the_approved_one(
    h: Harness,
) -> None:
    item = await create(h, answer="B", answerSource="source-key")
    iid = item["itemId"]
    await act(h, iid, "submit", AUTHOR)
    approved = await act(h, iid, "approve", REVIEWER)
    v2 = await edit(h, approved, AUTHOR, stem="If 3(c + d) = 5, find c + d.")
    assert v2["state"] == "draft" and v2["currentVersion"] == 2 and v2["approvedVersion"] == 1
    full = await call(h, "GET", f"{ITEMS}/{iid}", AUTHOR, 200)
    v1 = full["versions"][0]
    assert v1["state"] == "approved" and v1["stem"].startswith("If 3(c + d) = 5, what")
    await act(h, iid, "submit", AUTHOR)
    final = await act(h, iid, "approve", REVIEWER)
    assert final["approvedVersion"] == 2 and final["current"]["number"] == 2


async def test_reject_needs_notes_and_a_rejected_item_is_revised_as_a_new_version(
    h: Harness,
) -> None:
    item = await create(h)
    iid = item["itemId"]
    await act(h, iid, "submit", AUTHOR)
    assert code(await act(h, iid, "reject", REVIEWER, 400, notes="")) == "VALIDATION_FAILED"
    rejected = await act(h, iid, "reject", REVIEWER, notes="Choice C duplicates B.")
    assert rejected["state"] == "rejected"
    assert rejected["current"]["review"]["notes"] == "Choice C duplicates B."
    revised = await edit(h, rejected, AUTHOR, choices={**MC["choices"], "C": "15"})
    assert revised["state"] == "draft" and revised["currentVersion"] == 2


async def test_discard_only_before_approval_and_retire_after(h: Harness) -> None:
    draft = await create(h)
    assert (await act(h, draft["itemId"], "discard", AUTHOR))["state"] == "discarded"
    assert (
        code(
            await edit(
                h,
                (await call(h, "GET", f"{ITEMS}/{draft['itemId']}", AUTHOR, 200)),
                AUTHOR,
                409,
                stem="x",
            )
        )
        == "INVALID_STATE_TRANSITION"
    )
    item = await create(h, answer="B", answerSource="source-key")
    iid = item["itemId"]
    await act(h, iid, "submit", AUTHOR)
    approved = await act(h, iid, "approve", REVIEWER)
    await edit(h, approved, AUTHOR, stem="new wording")  # v2 draft of an approved item
    err = await act(h, iid, "discard", AUTHOR, 409)
    assert code(err) == "INVALID_STATE_TRANSITION" and "retire" in err["error"]["message"]
    other = await create(h, answer="B", answerSource="source-key")
    await act(h, other["itemId"], "submit", AUTHOR)
    await act(h, other["itemId"], "approve", REVIEWER)
    retired = await act(h, other["itemId"], "retire", REVIEWER, notes="Duplicate of OG5 Q4.")
    assert retired["state"] == "retired"
    assert code(await act(h, other["itemId"], "submit", AUTHOR, 409)) == "INVALID_STATE_TRANSITION"


async def test_invalid_content_is_rejected(h: Harness) -> None:
    err = await call(h, "POST", ITEMS, AUTHOR, 400, {"content": {**MC, "answer": "B"}})
    assert "answerSource is required" in err["error"]["message"]
    spr = {**MC, "type": "spr"}  # spr items have no choices
    assert code(await call(h, "POST", ITEMS, AUTHOR, 400, {"content": spr})) == "VALIDATION_FAILED"
    assert await call(h, "POST", ITEMS, AUTHOR, 400, {"content": {**MC, "choices": {"E": "x"}}})


async def test_spr_reviewer_key_needs_a_solution(h: Harness) -> None:
    item = await create(h, type="spr", choices=None, stem="What is 1% more than 7000?")
    iid = item["itemId"]
    await act(h, iid, "submit", AUTHOR)
    await act(h, iid, "key", REVIEWER, answer="7070")
    err = await act(h, iid, "approve", REVIEWER, 409)
    assert code(err) == "ITEM_KEY_REQUIRED" and "solution" in err["error"]["message"]
    await act(h, iid, "key", REVIEWER, answer="7070", solution="7000 × 1.01 = 7070")
    assert (await act(h, iid, "approve", REVIEWER))["state"] == "approved"


# ---- Extracted items (the import path, Step 39) -------------------------------------------------


async def test_extracted_items_must_be_confirmed_before_review(h: Harness) -> None:
    actor = PlatformActor.for_member(AUTHOR, ActorRole.AUTHOR, "org_hsos_content")
    out = await h.services.bank.create(
        actor,
        CreateItemInput(content=ItemContent(stem="Extracted stem", item_type=ItemType.SPR)),
        CommandKey(scope="test", key=idem(), request_digest="d"),
        initial_state=BankItemState.EXTRACTED,
    )
    iid = out.value.item.item_id
    assert out.value.item.state is BankItemState.EXTRACTED
    assert code(await act(h, iid, "submit", AUTHOR, 409)) == "INVALID_STATE_TRANSITION"
    assert (await act(h, iid, "confirm", AUTHOR))["state"] == "draft"
    assert (await act(h, iid, "submit", AUTHOR))["state"] == "in_review"


async def test_me_tells_the_portal_whether_the_member_can_review(h: Harness) -> None:
    assert await call(h, "GET", "/api/bank/me", AUTHOR, 200) == {
        "uid": AUTHOR,
        "role": "author",
        "orgId": "org_hsos_content",
        "canReview": False,
    }
    assert (await call(h, "GET", "/api/bank/me", REVIEWER, 200))["canReview"] is True
    await call(h, "GET", "/api/bank/me", PLATFORM_REVIEWER, 403)
    await call(h, "GET", "/api/bank/me", STUDENT, 403)
