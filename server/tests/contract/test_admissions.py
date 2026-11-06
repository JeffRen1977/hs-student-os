"""Step 35: admissions interview → confirmed facts → outline/feedback; sourced deadlines;
activities grounded in confirmed facts. Model work runs as Runs through the worker with a
scripted provider (never real grading).

- 35.1 A model may only *propose* facts, each quoting the answer; unquoted ones are
  dropped; only confirmed facts reach an outline.
- 35.2 Deadlines are labeled verified / stale / unverified / unsourced.
- 35.3 Drafts are the student's; output is capped coaching items. Long prose is rejected.
- 35.4 Activities need the student's confirmation and confirmed facts only.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.support import Harness, ScriptedProvider, build_harness, idem

ALEX, BETH = "stu_alex", "stu_beth"
ANSWER = (
    "I volunteer at the Eastside food bank every Saturday morning. "
    "Last spring I started a math tutoring club with four friends."
)


@pytest.fixture
def provider() -> ScriptedProvider:
    return ScriptedProvider()


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch, provider: ScriptedProvider) -> Harness:
    harness = build_harness(clean_env, llm_provider=provider)
    for sid, ap in ((ALEX, ["calc_bc"]), (BETH, ["calc_bc"])):
        harness.put_doc(
            f"students/{sid}/access/current",
            {"apCourses": ap, "courses": ["dsat"] if sid == ALEX else [], "admissions": True,
             "updatedAt": harness.clock.now(), "updatedBy": "admin-test"},
        )  # fmt: skip
    return harness


async def post(h: Harness, path: str, body: dict[str, Any], status: int,
               uid: str = ALEX, key: str | None = None) -> Any:  # fmt: skip
    r = await h.client.post(path, json=body, headers=h.cmd(uid, key))
    assert r.status_code == status, r.text
    return r.json()


async def patch(h: Harness, path: str, body: dict[str, Any], version: int, status: int) -> Any:
    r = await h.client.patch(path, json=body, headers={**h.auth(ALEX), "If-Match": f'"{version}"'})
    assert r.status_code == status, r.text
    return r.json()


async def get(h: Harness, path: str, uid: str = ALEX, status: int = 200) -> Any:
    r = await h.client.get(path, headers=h.auth(uid))
    assert r.status_code == status, r.text
    return r.json()


async def run_status(h: Harness, run_id: str) -> dict[str, Any]:
    return dict(await get(h, f"/api/runs/{run_id}"))


async def interview(h: Harness, provider: ScriptedProvider) -> list[dict[str, Any]]:
    provider.queue(
        {
            "facts": [
                {
                    "text": "Volunteers at a food bank every Saturday",
                    "category": "activity",
                    "quote": "I volunteer at the Eastside food bank every Saturday morning.",
                },
                {
                    "text": "Founded a math tutoring club",
                    "category": "achievement",
                    "quote": "I started a math tutoring club with four friends",
                },
                {
                    "text": "Won a state science award",
                    "category": "achievement",
                    "quote": "I won the state science award",
                },  # never said: must be dropped
            ]
        }
    )
    accepted = await post(
        h, "/api/admissions/interview/answers", {"promptId": "activities", "text": ANSWER}, 202
    )
    await h.drain()
    run = await run_status(h, accepted["runId"])
    assert run["status"] == "SUCCEEDED" and run["kind"] == "ADMISSIONS_FACTS"
    assert run["sessionId"] is None and run["subjectId"] == accepted["answerId"]
    return list((await get(h, "/api/admissions/facts"))["facts"])


async def test_access_is_platform_managed(clean_env: pytest.MonkeyPatch) -> None:
    h = build_harness(clean_env)
    r = await h.client.get("/api/admissions/facts", headers=h.auth(ALEX))
    assert r.status_code == 403 and r.json()["error"]["code"] == "ADMISSIONS_ACCESS_REQUIRED"


async def test_interview_proposes_only_quoted_facts_and_student_decides(
    h: Harness, provider: ScriptedProvider
) -> None:
    facts = await interview(h, provider)
    assert [(f["text"], f["status"], f["source"]) for f in facts] == [
        ("Volunteers at a food bank every Saturday", "proposed", "interview"),
        ("Founded a math tutoring club", "proposed", "interview"),
    ]  # the unquoted "award" was never stored
    assert all(f["quote"] in ANSWER for f in facts)
    assert "Interview question:" in provider.calls[0]["system"]
    assert "<student_answer>" in provider.calls[0]["messages"][0].text

    food, club = facts
    confirmed = await post(
        h, f"/api/admissions/facts/{food['factId']}/confirm",
        {"text": "I volunteer at the food bank on Saturdays"}, 200,
    )  # fmt: skip
    assert confirmed["status"] == "confirmed"
    assert confirmed["text"] == "I volunteer at the food bank on Saturdays"
    await post(h, f"/api/admissions/facts/{club['factId']}/reject", {}, 200)
    again = await h.client.post(
        f"/api/admissions/facts/{club['factId']}/confirm", json={}, headers=h.cmd(ALEX)
    )
    assert again.status_code == 409  # a decision is final


async def make_essay(h: Harness, draft: str = "") -> dict[str, Any]:
    essay = await post(
        h, "/api/admissions/essays",
        {"title": "Personal statement", "prompt": "Describe a community you belong to."}, 201,
    )  # fmt: skip
    if draft:
        essay = await patch(h, f"/api/admissions/essays/{essay['essayId']}", {"draft": draft},
                            essay["version"], 200)  # fmt: skip
    return dict(essay)


async def test_outline_uses_only_confirmed_facts(h: Harness, provider: ScriptedProvider) -> None:
    essay = await make_essay(h)
    r = await h.client.post(
        f"/api/admissions/essays/{essay['essayId']}/feedback", json={"kind": "outline"},
        headers=h.cmd(ALEX),
    )  # fmt: skip
    assert r.status_code == 409 and r.json()["error"]["code"] == "FACTS_NOT_CONFIRMED"

    food, club = await interview(h, provider)
    await post(h, f"/api/admissions/facts/{food['factId']}/confirm", {}, 200)
    # `club` stays proposed: it must not reach the model.
    provider.queue(
        {
            "items": [
                {
                    "type": "outline_point",
                    "text": "Open with a Saturday shift at the food bank",
                    "factIds": [food["factId"]],
                },
                {
                    "type": "outline_point",
                    "text": "Show what serving neighbors taught you",
                    "factIds": [food["factId"]],
                },
            ]
        }
    )
    path = f"/api/admissions/essays/{essay['essayId']}/feedback"
    fb = await post(h, path, {"kind": "outline"}, 202)
    await h.drain()
    assert (await run_status(h, fb["runId"]))["status"] == "SUCCEEDED"
    system = provider.calls[-1]["system"]
    assert food["factId"] in system and club["factId"] not in system
    schema = provider.calls[-1]["output_schema"]
    assert schema["properties"]["items"]["items"]["properties"]["factIds"]["items"]["enum"] == [
        food["factId"]
    ]
    listed = (await get(h, f"/api/admissions/essays/{essay['essayId']}/feedback"))["feedback"]
    assert [i["type"] for i in listed[0]["items"]] == ["outline_point", "outline_point"]
    current = await get(h, f"/api/admissions/essays/{essay['essayId']}")
    assert current["draft"] == "" and current["activeRunId"] is None  # nothing was written


async def test_ghostwritten_output_is_rejected(h: Harness, provider: ScriptedProvider) -> None:
    draft = "Every Saturday I sort cans at the food bank. It taught me patience."
    essay = await make_essay(h, draft)
    prose = " ".join(["This is a polished paragraph the student could paste."] * 8)
    bad = {"items": [{"type": "suggestion", "text": prose, "factIds": []}]}
    provider.queue(bad, bad, bad)
    path = f"/api/admissions/essays/{essay['essayId']}/feedback"
    fb = await post(h, path, {"kind": "feedback"}, 202)
    # While the run is active the draft cannot change underneath it.
    essay_path = f"/api/admissions/essays/{essay['essayId']}"
    await patch(h, essay_path, {"draft": "x"}, essay["version"], 409)
    await h.drain()
    run = await run_status(h, fb["runId"])
    assert run["status"] == "FAILED" and run["error"]["code"] == "MODEL_OUTPUT_INVALID"
    listed = (await get(h, f"/api/admissions/essays/{essay['essayId']}/feedback"))["feedback"]
    assert listed[0]["items"] == []
    current = await get(h, f"/api/admissions/essays/{essay['essayId']}")
    assert current["draft"] == draft and current["activeRunId"] is None


async def test_feedback_on_the_students_own_draft(h: Harness, provider: ScriptedProvider) -> None:
    draft = "Every Saturday I sort cans at the food bank. It taught me patience."
    essay = await make_essay(h, draft)
    provider.queue(
        {
            "items": [
                {"type": "strength", "text": "The Saturday detail is concrete.", "factIds": []},
                {
                    "type": "question",
                    "text": "What changed in how you see your neighbors?",
                    "factIds": [],
                },
            ]
        }
    )
    path = f"/api/admissions/essays/{essay['essayId']}/feedback"
    fb = await post(h, path, {"kind": "feedback"}, 202)
    await h.drain()
    assert (await run_status(h, fb["runId"]))["status"] == "SUCCEEDED"
    assert "<student_draft>" in provider.calls[-1]["messages"][0].text
    assert (await get(h, f"/api/admissions/essays/{essay['essayId']}"))["draft"] == draft


async def test_activities_need_confirmation_and_confirmed_facts(
    h: Harness, provider: ScriptedProvider
) -> None:
    food, club = await interview(h, provider)
    body = {"name": "Food bank", "role": "Volunteer", "description": "Sort donations weekly.",
            "hoursPerWeek": 3, "weeksPerYear": 40, "factIds": [food["factId"]],
            "studentConfirmed": True}  # fmt: skip
    r = await h.client.post("/api/admissions/activities", json=body, headers=h.cmd(ALEX))
    assert r.status_code == 409 and r.json()["error"]["code"] == "FACTS_NOT_CONFIRMED"
    await post(h, f"/api/admissions/facts/{food['factId']}/confirm", {}, 200)
    r = await h.client.post(
        "/api/admissions/activities", json={**body, "studentConfirmed": False}, headers=h.cmd(ALEX)
    )
    assert r.status_code == 409
    activity = await post(h, "/api/admissions/activities", body, 201)
    # An edit is checked again: citing a still-proposed fact is refused.
    cited = {**body, "factIds": [food["factId"], club["factId"]]}
    await patch(h, f"/api/admissions/activities/{activity['activityId']}", cited, 1, 409)
    updated = await patch(
        h, f"/api/admissions/activities/{activity['activityId']}",
        {**body, "hoursPerWeek": 4}, 1, 200,
    )  # fmt: skip
    assert updated["hoursPerWeek"] == 4 and updated["version"] == 2
    await patch(h, f"/api/admissions/activities/{activity['activityId']}", body, 1, 409)


async def test_deadlines_carry_source_and_verification(h: Harness) -> None:
    today = h.clock.now().date()

    async def add(**kw: Any) -> dict[str, Any]:
        body = {"school": "Example University", "kind": "regular", "dueDate": "2027-01-01", **kw}
        return dict(await post(h, "/api/admissions/deadlines", body, 201))

    assert (await add())["verification"] == "unsourced"
    url = "https://admissions.example.edu/dates"
    assert (await add(sourceUrl=url))["verification"] == "unverified"
    fresh = await add(sourceUrl=url, sourceCheckedOn=today.isoformat())
    assert fresh["verification"] == "verified" and fresh["daysLeft"] > 0
    old = await add(sourceUrl=url, sourceCheckedOn="2026-08-01")
    assert old["verification"] == "stale" and "re-check" in old["uncertainty"]
    r = await h.client.post(
        "/api/admissions/deadlines",
        json={"school": "X", "kind": "regular", "dueDate": "2027-01-01",
              "sourceUrl": "http://insecure.example.edu"},
        headers=h.cmd(ALEX),
    )  # fmt: skip
    assert r.status_code == 400
    listed = (await get(h, "/api/admissions/deadlines"))["deadlines"]
    assert len(listed) == 4


async def test_admissions_data_is_isolated_and_idempotent(
    h: Harness, provider: ScriptedProvider
) -> None:
    key = idem()
    body = {"title": "Why us", "prompt": "Why this college?"}
    one = await post(h, "/api/admissions/essays", body, 201, key=key)
    two = await post(h, "/api/admissions/essays", body, 201, key=key)
    assert one["essayId"] == two["essayId"]
    await post(h, "/api/admissions/essays", {**body, "title": "Other"}, 409, key=key)
    await get(h, f"/api/admissions/essays/{one['essayId']}", BETH, 404)
    assert (await get(h, "/api/admissions/essays", BETH))["essays"] == []


async def test_without_a_model_admissions_runs_fail_plainly(clean_env: pytest.MonkeyPatch) -> None:
    h = build_harness(clean_env)  # HSOS_LLM_PROVIDER=mock: no synthetic admissions output
    h.put_doc(
        f"students/{ALEX}/access/current",
        {"apCourses": ["calc_bc"], "courses": ["dsat"], "admissions": True,
         "updatedAt": h.clock.now(), "updatedBy": "admin-test"},
    )  # fmt: skip
    accepted = await post(
        h, "/api/admissions/interview/answers", {"promptId": "goals", "text": "Engineering."}, 202
    )
    await h.drain()
    run = await run_status(h, accepted["runId"])
    assert run["status"] == "FAILED" and run["error"]["code"] == "MODEL_UNAVAILABLE"
    assert (await get(h, "/api/admissions/facts"))["facts"] == []
