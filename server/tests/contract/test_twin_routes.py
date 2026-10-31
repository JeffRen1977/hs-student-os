"""Steps 9–10: Twin reads, allowlisted patches, optimistic concurrency, isolation."""

from __future__ import annotations

import pytest

from app.bootstrap import build_services
from app.main import create_app
from app.schemas.student import Entitlements, TwinSummary
from tests.support import Harness, harness_settings


async def _twin(h: Harness, sid: str = "stu_alex") -> tuple[dict[str, object], str]:
    response = await h.client.get("/api/twin", headers=h.auth(sid))
    assert response.status_code == 200
    return response.json(), response.headers["ETag"]


async def test_get_twin_shape_and_etag(harness: Harness) -> None:
    body, etag = await _twin(harness)
    twin = TwinSummary.model_validate(body)
    assert etag == f'"{twin.version}"'
    assert twin.student_id == "stu_alex"
    assert twin.prediction_summary["calc_bc"].status == "unavailable"
    assert twin.latest_event_sequence == 0
    assert "entitlements" not in body and "contactEmail" not in body


async def test_patch_valid_fields_bumps_version(harness: Harness) -> None:
    _, etag = await _twin(harness)
    response = await harness.client.patch(
        "/api/twin",
        json={
            "profile": {"displayName": "Alex R.", "school": None},
            "goals": {"apTargets": {}},
            "preferences": {"weeklyAvailableMinutes": 240, "timezone": "America/Chicago"},
        },
        headers={**harness.auth("stu_alex"), "If-Match": etag},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert response.headers["ETag"] == '"2"' and body["version"] == 2
    assert body["profile"]["displayName"] == "Alex R."
    assert body["profile"]["school"] is None
    assert body["profile"]["targetMajor"] == "Computer Science"  # untouched leaf kept
    assert body["goals"]["apTargets"] == {}  # replaced, not merged
    assert body["goals"]["satTarget"] == 1550
    assert body["preferences"]["timezone"] == "America/Chicago"
    # Persisted, and Beth is unaffected.
    again, _ = await _twin(harness)
    assert again == body
    beth, _ = await _twin(harness, "stu_beth")
    assert beth["profile"]["displayName"] == "Beth" and beth["version"] == 1


@pytest.mark.parametrize(
    "body",
    [
        {"studentId": "stu_beth"},
        {"entitlements": {"apCourses": ["apush"], "dsat": True, "admissions": True}},
        {"version": 9},
        {"masterySummary": {}},
        {"predictionSummary": {"calc_bc": {"status": "available", "reason": "x"}}},
        {"subscriptions": ["calc_bc"]},
        {"profile": {"email": "new@example.test"}},
        {"preferences": {"entitlements": ["calc_bc"]}},
        {"profile": {"displayName": None}},
        {"preferences": {"timezone": "PST"}},
        {"preferences": {"selectedCourses": ["not_a_course"]}},
        {"profile": {}},
        {},
    ],
)
async def test_patch_rejects_forbidden_unknown_or_invalid(
    harness: Harness, body: dict[str, object]
) -> None:
    response = await harness.client.patch(
        "/api/twin", json=body, headers={**harness.auth("stu_alex"), "If-Match": '"1"'}
    )
    assert response.status_code == 400, body
    twin, _ = await _twin(harness)
    assert twin["version"] == 1


async def test_patch_with_stale_version_is_409(harness: Harness) -> None:
    headers = {**harness.auth("stu_alex"), "If-Match": '"1"'}
    first = await harness.client.patch(
        "/api/twin", json={"profile": {"grade": 12}}, headers=headers
    )
    assert first.status_code == 200
    stale = await harness.client.patch(
        "/api/twin", json={"profile": {"grade": 10}}, headers=headers
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "VERSION_CONFLICT"
    twin, _ = await _twin(harness)
    assert twin["profile"]["grade"] == 12


async def test_patch_without_if_match_is_428(harness: Harness) -> None:
    response = await harness.client.patch(
        "/api/twin", json={"profile": {"grade": 12}}, headers=harness.auth("stu_alex")
    )
    assert response.status_code == 428
    assert response.json()["error"]["code"] == "PRECONDITION_REQUIRED"


async def test_patch_with_malformed_if_match_is_400(harness: Harness) -> None:
    response = await harness.client.patch(
        "/api/twin",
        json={"profile": {"grade": 12}},
        headers={**harness.auth("stu_alex"), "If-Match": "1"},
    )
    assert response.status_code == 400


async def test_entitlements_are_read_only(harness: Harness) -> None:
    response = await harness.client.get("/api/me/entitlements", headers=harness.auth("stu_beth"))
    assert response.status_code == 200
    assert Entitlements.model_validate(response.json()).dsat is False
    for method in ("PATCH", "POST", "PUT"):
        attempt = await harness.client.request(
            method,
            "/api/me/entitlements",
            json={"dsat": True},
            headers=harness.cmd("stu_beth"),
        )
        assert attempt.status_code == 405, method
    again = await harness.client.get("/api/me/entitlements", headers=harness.auth("stu_beth"))
    assert again.json()["dsat"] is False


async def test_selecting_a_course_grants_nothing(harness: Harness) -> None:
    response = await harness.client.patch(
        "/api/twin",
        json={"preferences": {"selectedCourses": ["calc_bc", "apush", "dsat"]}},
        headers={**harness.auth("stu_beth"), "If-Match": '"1"'},
    )
    assert response.status_code == 200
    ent = await harness.client.get("/api/me/entitlements", headers=harness.auth("stu_beth"))
    assert ent.json() == {"apCourses": ["calc_bc"], "dsat": False, "admissions": False}
    catalog = await harness.client.get("/api/courses/catalog", headers=harness.auth("stu_beth"))
    dsat = next(c for c in catalog.json()["courses"] if c["courseId"] == "dsat")
    assert dsat["entitled"] is False and dsat["enrolled"] is False
    enroll = await harness.client.post(
        "/api/courses/enroll", json={"courseId": "dsat"}, headers=harness.cmd("stu_beth")
    )
    assert enroll.status_code == 409  # planned; and Beth has no dsat entitlement either


async def test_data_survives_restart(harness: Harness, clean_env: pytest.MonkeyPatch) -> None:
    await harness.client.patch(
        "/api/twin",
        json={"profile": {"grade": 12}},
        headers={**harness.auth("stu_alex"), "If-Match": '"1"'},
    )
    # A fresh app + services over the same retained store: nothing lived only in memory
    # of the previous process.
    settings = harness_settings(clean_env)
    services = build_services(settings, store=harness.store, clock=harness.clock)
    from httpx import ASGITransport, AsyncClient

    client = AsyncClient(
        transport=ASGITransport(app=create_app(settings, services)), base_url="http://t"
    )
    response = await client.get("/api/twin", headers=harness.auth("stu_alex"))
    assert response.json()["profile"]["grade"] == 12 and response.json()["version"] == 2
