"""Publication gate, atomic audit, and duplicate publication on real Firestore."""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import Any

import pytest

from app.registries.content import DEFAULT_CONTENT_ROOT
from tests.emulator.test_firestore_flows import make_env
from tests.support import emulator_token, idem


@pytest.fixture
async def env() -> Any:
    return await make_env()


def headers(env: dict[str, Any], uid: str, key: str | None = None) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {emulator_token(uid, now=env['clock'].now())}",
        "Idempotency-Key": key or idem(),
    }


async def prepare(env: dict[str, Any]) -> tuple[str, str]:
    # No underscore: the replace below also rewrites rubric IDs and the workflow version,
    # which are slugs.
    course = "lab" + secrets.token_hex(4)
    text = (DEFAULT_CONTENT_ROOT / "authored/dsat/package.json").read_text()
    pkg = json.loads(text.replace("dsat", course))
    http = env["http"]
    r = await http.post(
        "/api/authoring/packages", json={"package": pkg}, headers=headers(env, "author_hsos")
    )
    assert r.status_code == 201, r.text
    base = f"/packages/{course}/versions/1.0.0"
    r = await http.post(
        "/api/authoring" + base + "/submit", json={}, headers=headers(env, "author_hsos")
    )
    assert r.status_code == 200, r.text
    r = await http.post(
        "/api/review" + base + "/approve",
        json={"licenseAttested": True},
        headers=headers(env, "reviewer_platform"),
    )
    assert r.status_code == 200, r.text
    return course, "/api/admin" + base + "/activate"


async def test_publish_commits_pointer_and_admin_audit_then_all_students_enroll(
    env: dict[str, Any],
) -> None:
    course, path = await prepare(env)
    r = await env["http"].post(path, json={}, headers=headers(env, "admin_platform"))
    assert r.status_code == 200, r.text
    record = (await env["db"].document(f"packageCourses/{course}").get()).to_dict()
    version = (await env["db"].document(f"packageVersions/{course}@1.0.0").get()).to_dict()
    assert record["activeVersion"] == "1.0.0" and version["status"] == "active"
    assert version["history"][-1]["actorId"] == "admin_platform"
    for sid in (env["alex"], env["beth"]):
        access = (await env["db"].document(f"students/{sid}/access/current").get()).to_dict()
        assert course not in access.get("courses", [])
        r = await env["http"].post(
            "/api/courses/enroll", json={"courseId": course}, headers=headers(env, sid)
        )
        assert r.status_code == 200, r.text


async def test_concurrent_duplicate_publication_has_one_transition(env: dict[str, Any]) -> None:
    _, path = await prepare(env)
    auth = headers(env, "admin_platform", idem())
    a, b = await asyncio.gather(
        env["http"].post(path, json={}, headers=auth),
        env["http"].post(path, json={}, headers=auth),
    )
    assert a.status_code == b.status_code == 200, (a.text, b.text)
    assert sum(x["toStatus"] == "active" for x in b.json()["history"]) == 1
