"""Step 41: the reviewer screen's use of the existing review API.

The screen (web/review.html) adds no authority: it calls only `/api/review/*`, and the
server checks the platform reviewer role on each call. These tests pin exactly what the
screen relies on: role gating on every endpoint it calls, the all-status queue it builds its
lists from (drafts never included), the full package with answer keys for reviewers only,
and a queue → active and a queue → rejected path whose history matches the actions.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.contract.test_package_review import (
    ALEX,
    APPROVE,
    AUTHOR,
    BASE,
    COURSE,
    REVIEW,
    REVIEWER,
    get,
    package,
    post,
    upload,
)
from tests.support import Harness, build_harness

ALL = "?" + "&".join(
    f"status={s}" for s in ("submitted", "approved", "active", "superseded", "rejected", "retired")
)


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch) -> Harness:
    return build_harness(clean_env)


async def submitted(h: Harness, version: str) -> None:
    await upload(h, package(version))
    await post(h, f"{BASE}/{version}/submit", AUTHOR, {}, 200)


def listed(queue: dict[str, Any]) -> dict[str, str]:
    return {v["version"]: v["status"] for v in queue["versions"] if v["courseId"] == COURSE}


async def test_every_endpoint_the_screen_calls_is_reviewer_only(h: Harness) -> None:
    await submitted(h, "1.0.0")
    v = f"{REVIEW}/1.0.0"
    for uid in (AUTHOR, ALEX):
        await get(h, f"/api/review/packages{ALL}", uid, status=403)
        await get(h, v, uid, status=403)
        await get(h, f"{v}/preview", uid, status=403)
        await post(h, f"{v}/approve", uid, APPROVE, 403)
        await post(h, f"{v}/reject", uid, {"notes": "no"}, 403)
        await post(h, f"{v}/activate", uid, {}, 403)
        await post(h, f"/api/review/courses/{COURSE}/retire", uid, {"notes": "no"}, 403)
    assert listed(await get(h, f"/api/review/packages{ALL}", REVIEWER)) == {"1.0.0": "submitted"}


async def test_the_full_package_with_keys_is_for_reviewers_only(h: Harness) -> None:
    await submitted(h, "1.0.0")
    full = await get(h, f"{REVIEW}/1.0.0", REVIEWER)
    items = [i for q in full["package"]["questions"] for i in q["items"]]
    assert items and all(i["answerKey"] for i in items)
    preview = await get(h, f"{REVIEW}/1.0.0/preview", REVIEWER)
    assert "answerKey" not in json.dumps(preview) and "rubric" not in json.dumps(preview)
    assert "answerKey" not in json.dumps(await get(h, f"{BASE}/1.0.0/preview", AUTHOR))


async def test_queue_to_active_and_to_rejected_with_matching_history(h: Harness) -> None:
    await submitted(h, "1.0.0")
    await submitted(h, "1.1.0")
    await upload(h, package("1.2.0"))  # a draft: never in the reviewer's lists
    assert listed(await get(h, f"/api/review/packages{ALL}", REVIEWER)) == {
        "1.0.0": "submitted",
        "1.1.0": "submitted",
    }

    await post(h, f"{REVIEW}/1.0.0/approve", REVIEWER, APPROVE, 200)
    await post(h, f"{REVIEW}/1.0.0/activate", REVIEWER, {}, 200)
    notes = "Item 2 of the first set has two defensible answers."
    await post(h, f"{REVIEW}/1.1.0/reject", REVIEWER, {"notes": notes}, 200)
    # Reject needs notes; a decided version takes no further decision.
    r = await post(h, f"{REVIEW}/1.1.0/approve", REVIEWER, APPROVE, 409)
    assert r["error"]["code"] == "INVALID_STATE_TRANSITION"
    r = await h.client.post(f"{REVIEW}/1.0.0/reject", json={"notes": ""}, headers=h.cmd(REVIEWER))
    assert r.status_code == 400 and r.json()["error"]["code"] == "VALIDATION_FAILED"

    assert listed(await get(h, f"/api/review/packages{ALL}", REVIEWER)) == {
        "1.0.0": "active",
        "1.1.0": "rejected",
    }
    active = await get(h, f"{REVIEW}/1.0.0", REVIEWER)
    assert [(x["fromStatus"], x["toStatus"], x["actorId"]) for x in active["history"]] == [
        (None, "draft", AUTHOR),
        ("draft", "submitted", AUTHOR),
        ("submitted", "approved", REVIEWER),
        ("approved", "active", REVIEWER),
    ]
    assert active["review"]["licenseAttested"] is True
    rejected = await get(h, f"{REVIEW}/1.1.0", REVIEWER)
    assert rejected["history"][-1] == {
        **rejected["history"][-1],
        "toStatus": "rejected",
        "actorId": REVIEWER,
        "notes": notes,
    }
    # The author sees the reviewer's notes on their own version.
    own = await get(h, f"{BASE}/1.1.0", AUTHOR)
    assert own["status"] == "rejected" and own["review"]["notes"] == notes
