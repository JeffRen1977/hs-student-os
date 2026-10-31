"""Step 8: every API route authenticates; identity only from verified tokens."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tests.support import START, Harness, emulator_token, make_task

PROTECTED = [
    ("GET", "/api/twin"),
    ("PATCH", "/api/twin"),
    ("GET", "/api/me/entitlements"),
    ("GET", "/api/courses/catalog"),
    ("GET", "/api/courses/enrolled"),
    ("POST", "/api/courses/enroll"),
    ("GET", "/api/tasks"),
    ("POST", "/api/sessions"),
    ("GET", "/api/runs/run_x"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_missing_token_is_401(harness: Harness, method: str, path: str) -> None:
    response = await harness.client.request(method, path, json={})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@pytest.mark.parametrize(
    "header",
    ["Basic abc", "Bearer", "Bearer a b", "token"],
)
async def test_malformed_authorization_is_401(harness: Harness, header: str) -> None:
    response = await harness.client.get("/api/twin", headers={"Authorization": header})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "claims",
    [
        {"exp": int((START - timedelta(hours=1)).timestamp())},
        {"aud": "another-project"},
    ],
    ids=["expired", "wrong-audience"],
)
async def test_invalid_tokens_are_401(harness: Harness, claims: dict[str, object]) -> None:
    token = emulator_token("stu_alex", **claims)
    response = await harness.client.get("/api/twin", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_valid_token_resolves_own_student(harness: Harness) -> None:
    response = await harness.client.get("/api/twin", headers=harness.auth("stu_beth"))
    assert response.status_code == 200
    assert response.json()["studentId"] == "stu_beth"
    # First verified login records the uid → studentId mapping.
    assert harness.store.raw("identities/stu_beth") == {"uid": "stu_beth", "studentId": "stu_beth"}


async def test_identity_mapping_decides_student(harness: Harness) -> None:
    harness.put_doc(
        "identities/firebase_uid_123", {"uid": "firebase_uid_123", "studentId": "stu_alex"}
    )
    response = await harness.client.get("/api/twin", headers=harness.auth("firebase_uid_123"))
    assert response.json()["studentId"] == "stu_alex"


async def test_unprovisioned_account_is_403(harness: Harness) -> None:
    response = await harness.client.get("/api/twin", headers=harness.auth("stu_unknown"))
    assert response.status_code == 403
    assert harness.store.raw("students/stu_unknown") is None  # never auto-created


async def test_x_user_email_is_rejected(harness: Harness) -> None:
    response = await harness.client.get(
        "/api/twin",
        headers={**harness.auth("stu_beth"), "X-User-Email": "alex.synthetic@example.test"},
    )
    assert response.status_code == 400
    assert "x-user-email" in response.json()["error"]["message"]


async def test_student_id_query_param_is_rejected(harness: Harness) -> None:
    response = await harness.client.get(
        "/api/twin?studentId=stu_alex", headers=harness.auth("stu_beth")
    )
    assert response.status_code == 400


async def test_body_student_id_is_rejected(harness: Harness) -> None:
    response = await harness.client.post(
        "/api/sessions",
        json={"taskId": "task_alex_calc_01", "studentId": "stu_alex"},
        headers=harness.cmd("stu_beth"),
    )
    assert response.status_code == 400


async def test_service_prefixed_subject_cannot_sign_in(harness: Harness) -> None:
    response = await harness.client.get("/api/twin", headers=harness.auth("svc:run-worker"))
    assert response.status_code == 401


async def test_student_b_cannot_reach_student_a_resources(harness: Harness) -> None:
    harness.put_task(make_task("stu_alex", "task_private"))
    beth = harness.auth("stu_beth")
    for path in ("/api/tasks/task_private", "/api/tasks/task_alex_calc_01"):
        response = await harness.client.get(path, headers=beth)
        assert response.status_code == 404, path
    response = await harness.client.post(
        "/api/sessions", json={"taskId": "task_alex_calc_01"}, headers=harness.cmd("stu_beth")
    )
    assert response.status_code == 404
