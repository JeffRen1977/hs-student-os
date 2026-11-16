"""Step 45.4: selections of approved bank items and the deterministic package build.

The content reviewer selects approved item versions into sets, then builds a draft package
version that goes through the normal validator and platform review gate. Uses synthetic
items only; the base package is the seeded Digital SAT package of org_hsos_content.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.domain.bank_builder import build_package
from app.domain.commands import CommandKey
from app.domain.types.actor import ActorRole, PlatformActor
from app.domain.types.bank import Provenance, ProvenanceKind
from tests.support import Harness, build_harness, idem

AUTHOR, REVIEWER, OTHER = "author_hsos", "reviewer_hsos", "author_sample"
PLATFORM_REVIEWER = "reviewer_platform"
ORG = "org_hsos_content"
SKILL = "dsat.algebra.linear-equations"
ITEMS, SELECTIONS = "/api/bank/items", "/api/bank/selections"


def mc(stem: str, answer: str = "B", **extra: Any) -> dict[str, Any]:
    return {
        "stem": stem,
        "type": "mc",
        "choices": {"A": "1", "B": "2", "C": "3", "D": "4"},
        "answer": answer,
        "answerSource": "source-key",
        **extra,
    }


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch) -> Harness:
    return build_harness(clean_env)  # seeds the dsat package for org_hsos_content


async def call(h: Harness, method: str, path: str, uid: str, status: int, body: Any = None) -> Any:
    if method == "GET":
        r = await h.client.get(path, headers=h.auth(uid))
    else:
        r = await h.client.request(method, path, json=body or {}, headers=h.cmd(uid))
    assert r.status_code == status, r.text
    return r.json()


async def approved(h: Harness, content: dict[str, Any]) -> str:
    item = await call(h, "POST", ITEMS, AUTHOR, 201, {"courseId": "dsat", "content": content})
    iid = item["itemId"]
    await call(h, "POST", f"{ITEMS}/{iid}/submit", AUTHOR, 200)
    await call(h, "POST", f"{ITEMS}/{iid}/approve", REVIEWER, 200)
    return str(iid)


async def passage(h: Harness, text: str = "A synthetic passage about tide pools.") -> str:
    actor = PlatformActor.for_member(AUTHOR, ActorRole.AUTHOR, ORG)
    cmd = CommandKey(scope="test", key=idem(), request_digest="d")
    out = await h.services.bank.create_passage(
        actor, "Questions 1-2", text, Provenance(kind=ProvenanceKind.AUTHOR), cmd
    )
    return out.value.passage_id


def selection(sets: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "courseId": "dsat",
        "name": "Synthetic practice",
        "sets": sets,
        "starterSetIds": [sets[0]["setId"]],
        **extra,
    }


def a_set(set_id: str, *item_ids: str, **extra: Any) -> dict[str, Any]:
    return {
        "setId": set_id,
        "title": f"Set {set_id}",
        "taskTitle": f"Practice {set_id}",
        "items": [{"itemId": i} for i in item_ids],
        "skillIds": [SKILL],
        **extra,
    }


async def two_sets(h: Harness) -> dict[str, Any]:
    algebra = [await approved(h, mc(f"Algebra item {n}")) for n in (1, 2)]
    pid = await passage(h)
    reading = [await approved(h, mc(f"Reading item {n}", passageId=pid)) for n in (1, 2)]
    body = selection(
        [a_set("algebra-1", *algebra), a_set("reading-1", *reading)],
        sequenceSetIds=["reading-1"],
        sourceType="licensed",
        sourceAuthor="Synthetic Test Press",
        sourceLicense="Internal test only",
    )
    return await call(h, "POST", SELECTIONS, REVIEWER, 201, body)


# ---- Selections ------------------------------------------------------------------------------


async def test_content_reviewer_selects_approved_items_and_versions_are_pinned(h: Harness) -> None:
    sel = await two_sets(h)
    assert [s["setId"] for s in sel["sets"]] == ["algebra-1", "reading-1"]
    assert all(r["version"] == 1 for s in sel["sets"] for r in s["items"])
    assert sel["starterSetIds"] == ["algebra-1"] and sel["sequenceSetIds"] == ["reading-1"]
    listed = await call(h, "GET", SELECTIONS, AUTHOR, 200)  # authors can read
    assert [x["selectionId"] for x in listed["selections"]] == [sel["selectionId"]]
    await call(h, "GET", f"{SELECTIONS}/{sel['selectionId']}", OTHER, 404)


async def test_authors_cannot_write_or_build_selections(h: Harness) -> None:
    iid = await approved(h, mc("x"))
    await call(h, "POST", SELECTIONS, AUTHOR, 403, selection([a_set("s1", iid)]))
    await call(h, "GET", SELECTIONS, PLATFORM_REVIEWER, 403)


async def test_only_approved_items_and_well_formed_sets_are_accepted(h: Harness) -> None:
    good = await approved(h, mc("ok"))
    draft = (await call(h, "POST", ITEMS, AUTHOR, 201, {"content": mc("draft")}))["itemId"]
    err = await call(h, "POST", SELECTIONS, REVIEWER, 409, selection([a_set("s1", good, draft)]))
    assert err["error"]["code"] == "ITEM_NOT_APPROVED" and draft in err["error"]["message"]

    spr = await approved(h, {"stem": "What is 2 + 2?", "type": "spr", "answer": "4",
                             "answerSource": "source-key"})  # fmt: skip
    err = await call(h, "POST", SELECTIONS, REVIEWER, 409, selection([a_set("s1", good, spr)]))
    assert (
        err["error"]["code"] == "SELECTION_INVALID" and "cannot be built" in err["error"]["message"]
    )

    pid = await passage(h)
    p1, p2 = [await approved(h, mc(f"p{n}", passageId=pid)) for n in (1, 2)]
    split = selection([a_set("s1", p1), a_set("s2", p2)])
    err = await call(h, "POST", SELECTIONS, REVIEWER, 409, split)
    assert "split across sets" in err["error"]["message"]

    dup = selection([a_set("s1", good), a_set("s2", good)], sequenceSetIds=["nope"])
    message = (await call(h, "POST", SELECTIONS, REVIEWER, 409, dup))["error"]["message"]
    assert "used more than once" in message and "not in the selection: nope" in message


async def test_selection_rejects_items_targeted_at_a_different_course(h: Harness) -> None:
    iid = await approved(h, mc("Course-specific question"))
    body = {**selection([a_set("s1", iid)]), "courseId": "geolab"}
    err = await call(h, "POST", SELECTIONS, REVIEWER, 409, body)
    assert err["error"]["code"] == "SELECTION_INVALID"
    assert "belongs to course dsat" in err["error"]["message"]


async def test_picker_query_includes_previous_approved_versions(h: Harness) -> None:
    iid = await approved(h, mc("Originally approved"))
    item = await call(h, "GET", f"{ITEMS}/{iid}", AUTHOR, 200)
    await call(h, "PATCH", f"{ITEMS}/{iid}", AUTHOR, 200,
               {"expectedRevision": item["revision"], "changes": {"stem": "New draft"}})
    listed = await call(h, "GET", f"{ITEMS}?approvedOnly=true&courseId=dsat", REVIEWER, 200)
    assert [i["itemId"] for i in listed["items"]] == [iid]
    assert listed["items"][0]["state"] == "draft"
    selected = await call(h, "POST", SELECTIONS, REVIEWER, 201,
                          selection([a_set("s1", iid)]))
    assert selected["sets"][0]["items"][0]["version"] == 1


async def test_update_needs_the_current_revision(h: Harness) -> None:
    sel = await two_sets(h)
    body = {"expectedRevision": 1, "selection": {**selection(sel["sets"]), "name": "Renamed"}}
    body["selection"].pop("courseId")
    body["selection"]["sets"] = [
        {k: v for k, v in s.items()} for s in sel["sets"]
    ]  # views carry pinned versions; reuse them as input
    path = f"{SELECTIONS}/{sel['selectionId']}"
    assert (await call(h, "PATCH", path, REVIEWER, 200, body))["revision"] == 2
    assert (await call(h, "PATCH", path, REVIEWER, 409, body))["error"][
        "code"
    ] == "VERSION_CONFLICT"


# ---- Build ------------------------------------------------------------------------------------


async def test_build_produces_a_valid_draft_that_goes_through_the_review_gate(h: Harness) -> None:
    sel = await two_sets(h)
    built = await call(
        h, "POST", f"{SELECTIONS}/{sel['selectionId']}/build", REVIEWER, 201, {"version": "9.0.0"}
    )
    assert built["selection"]["builtPackageVersion"] == "9.0.0"
    pkg = built["package"]
    assert pkg["status"] == "draft" and pkg["report"]["valid"], pkg["report"]
    ev = pkg["report"]["evaluation"]
    assert ev["autoCases"] == ev["autoPassed"] == 5  # 2 all-correct, 2 one-wrong, 1 unreadable

    full = await call(h, "GET", "/api/authoring/packages/dsat/versions/9.0.0", REVIEWER, 200)
    content = full["package"]
    q_alg, q_read = content["questions"]
    assert [i["answerKey"] for i in q_alg["items"]] == ["B", "B"]
    assert q_alg["review"] == {"status": "reviewed", "reviewer": REVIEWER,
                               "reviewedAt": q_alg["review"]["reviewedAt"]}  # fmt: skip
    assert q_alg["source"]["type"] == "licensed" and len(q_alg["source"]["bankItems"]) == 2
    assert "tide pools" in q_read["prompt"]
    assert [t["questionId"] for t in content["starterTasks"]] == [q_alg["questionId"]]
    assert [t["questionId"] for t in content["practiceSequence"]] == [q_read["questionId"]]
    assert content["materials"] == [] and "choice-scoring" in content["manifest"]["abilities"]

    await call(h, "POST", "/api/authoring/packages/dsat/versions/9.0.0/submit", REVIEWER, 200)
    approve = {"notes": "ok", "licenseAttested": True}
    review = "/api/review/packages/dsat/versions/9.0.0/approve"
    assert (await call(h, "POST", review, PLATFORM_REVIEWER, 200, approve))["status"] == "approved"


async def test_build_replays_and_pins_versions_despite_later_edits(h: Harness) -> None:
    sel = await two_sets(h)
    first_item = sel["sets"][0]["items"][0]["itemId"]
    item = await call(h, "GET", f"{ITEMS}/{first_item}", AUTHOR, 200)
    body = {"expectedRevision": item["revision"], "changes": {"stem": "Edited after selection"}}
    await call(h, "PATCH", f"{ITEMS}/{first_item}", AUTHOR, 200, body)

    path = f"{SELECTIONS}/{sel['selectionId']}/build"
    headers = h.cmd(REVIEWER)
    a = await h.client.post(path, json={"version": "9.1.0"}, headers=headers)
    b = await h.client.post(path, json={"version": "9.1.0"}, headers=headers)
    assert a.status_code == b.status_code == 201 and b.headers.get("Idempotency-Replayed") == "true"
    full = await call(h, "GET", "/api/authoring/packages/dsat/versions/9.1.0", REVIEWER, 200)
    assert full["package"]["questions"][0]["items"][0]["prompt"] == "Algebra item 1"


async def test_replay_of_older_build_returns_its_original_package(h: Harness) -> None:
    sel = await two_sets(h)
    path = f"{SELECTIONS}/{sel['selectionId']}/build"
    first_headers = h.cmd(REVIEWER)
    first = await h.client.post(path, json={"version": "9.1.0"}, headers=first_headers)
    assert first.status_code == 201, first.text
    await call(h, "POST", path, REVIEWER, 201, {"version": "9.2.0"})
    replay = await h.client.post(path, json={"version": "9.1.0"}, headers=first_headers)
    assert replay.status_code == 201, replay.text
    assert replay.headers.get("Idempotency-Replayed") == "true"
    assert replay.json()["package"]["version"] == "9.1.0"

    current = await call(h, "GET", f"{SELECTIONS}/{sel['selectionId']}", REVIEWER, 200)
    changed = selection(current["sets"], name="Edited after both builds",
                        sequenceSetIds=current["sequenceSetIds"])
    changed.pop("courseId")
    await call(h, "PATCH", f"{SELECTIONS}/{sel['selectionId']}", REVIEWER, 200,
               {"expectedRevision": current["revision"], "selection": changed})
    replay = await h.client.post(path, json={"version": "9.1.0"}, headers=first_headers)
    assert replay.status_code == 201, replay.text
    assert replay.json()["package"]["version"] == "9.1.0"
    assert replay.json()["selection"]["builtPackageVersion"] is None


async def test_build_rejects_a_selection_changed_during_upload(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    sel = await two_sets(h)
    path = f"{SELECTIONS}/{sel['selectionId']}"
    upload = h.services.packages.upload

    async def edit_during_upload(actor: Any, raw: Any, cmd: Any) -> Any:
        changed = selection(sel["sets"], name="Changed during build",
                            sequenceSetIds=sel["sequenceSetIds"])
        changed.pop("courseId")
        await call(h, "PATCH", path, REVIEWER, 200,
                   {"expectedRevision": sel["revision"], "selection": changed})
        return await upload(actor, raw, cmd)

    monkeypatch.setattr(h.services.packages, "upload", edit_during_upload)
    err = await call(h, "POST", path + "/build", REVIEWER, 409, {"version": "9.3.0"})
    assert err["error"]["code"] == "VERSION_CONFLICT"
    current = await call(h, "GET", path, REVIEWER, 200)
    assert current["name"] == "Changed during build"
    assert current["builtPackageVersion"] is None


async def test_build_refuses_retired_items_and_courses_without_a_base_package(h: Harness) -> None:
    sel = await two_sets(h)
    retired = sel["sets"][1]["items"][0]["itemId"]
    await call(h, "POST", f"{ITEMS}/{retired}/retire", REVIEWER, 200, {"notes": "dup"})
    err = await call(
        h, "POST", f"{SELECTIONS}/{sel['selectionId']}/build", REVIEWER, 409, {"version": "9.0.0"}
    )
    assert err["error"]["code"] == "SELECTION_INVALID"

    iid = (await call(h, "POST", ITEMS, AUTHOR, 201, {"content": mc("new course item")}))["itemId"]
    await call(h, "POST", f"{ITEMS}/{iid}/submit", AUTHOR, 200)
    await call(h, "POST", f"{ITEMS}/{iid}/approve", REVIEWER, 200)
    other = await call(
        h,
        "POST",
        SELECTIONS,
        REVIEWER,
        201,
        {**selection([a_set("s1", iid)]), "courseId": "geolab"},
    )
    err = await call(
        h, "POST", f"{SELECTIONS}/{other['selectionId']}/build", REVIEWER, 409, {"version": "1.0.0"}
    )
    assert "upload a first package for geolab" in err["error"]["message"]


async def test_the_builder_is_deterministic(h: Harness) -> None:
    sel = await two_sets(h)
    actor = PlatformActor.for_member(REVIEWER, ActorRole.CONTENT_REVIEWER, ORG)
    stored = await h.services.selections.get(actor, sel["selectionId"])
    versions, passages = {}, {}
    for s in stored.sets:
        for r in s.items:
            detail = await h.services.bank.get_item(actor, r.item_id)
            v = next(v for v in detail.versions if v.number == r.version)
            versions[(r.item_id, r.version)] = v
            if v.content.passage_id:
                passages[v.content.passage_id] = await h.services.bank.get_passage(
                    actor, v.content.passage_id
                )
    pkgs = [p for p in await h.services.packages.list_own(actor) if p.course_id == "dsat"]
    base = json.loads(
        (await h.services.packages.get_own(actor, "dsat", pkgs[0].version)).package_json
    )
    one = build_package(base, stored, versions, passages, "9.0.0")
    two = build_package(base, stored, dict(reversed(list(versions.items()))), passages, "9.0.0")
    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)
