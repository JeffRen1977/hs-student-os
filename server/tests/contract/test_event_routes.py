"""Step 19: durable per-student event feed over polling and SSE."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.support import Harness, build_harness

SID = "stu_alex"


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch) -> Harness:
    # Tiny stream timings so a whole SSE connection fits in a test.
    return build_harness(
        clean_env, sse_heartbeat_seconds=0.05, sse_poll_seconds=0.02, sse_max_stream_seconds=0.3
    )


async def make_events(h: Harness, sid: str = SID, task: str = "task_alex_calc_01") -> None:
    r = await h.client.post("/api/sessions", json={"taskId": task}, headers=h.cmd(sid))
    assert r.status_code == 201
    session_id = r.json()["sessionId"]
    r = await h.client.post(
        f"/api/sessions/{session_id}/messages", json={"text": "hello"}, headers=h.cmd(sid)
    )
    assert r.status_code == 202
    await h.drain()  # synthetic executor: run.started + run.completed


async def poll(h: Harness, query: str, sid: str = SID) -> Any:
    r = await h.client.get(f"/api/events{query}", headers=h.auth(sid))
    assert r.status_code == 200, r.text
    return r.json()


def parse_sse(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    frames, comments = [], []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if line.startswith(":"):
                comments.append(line[1:].strip())
            else:
                key, _, value = line.partition(": ")
                fields[key] = value
        if "data" in fields:
            frames.append({**fields, "data": json.loads(fields["data"])})
    return frames, comments


async def test_events_are_ordered_paginated_and_replayable(h: Harness) -> None:
    await make_events(h)
    page = await poll(h, "?after=0&limit=2")
    assert [e["sequence"] for e in page["events"]] == [1, 2]
    assert page["hasMore"] is True and page["nextAfter"] == 2
    rest = await poll(h, f"?after={page['nextAfter']}")
    seqs = [e["sequence"] for e in rest["events"]]
    assert seqs == list(range(3, 3 + len(seqs))) and rest["hasMore"] is False
    types = [e["type"] for e in page["events"] + rest["events"]]
    assert types == ["session.started", "run.queued", "run.started", "run.completed"]
    # Reconnecting with an older cursor replays exactly what came after it.
    replay = await poll(h, "?after=1")
    assert [e["sequence"] for e in replay["events"]] == [2, 3, 4]
    empty = await poll(h, f"?after={seqs[-1]}")
    assert empty == {"events": [], "nextAfter": seqs[-1], "hasMore": False}
    twin = await h.client.get("/api/twin", headers=h.auth(SID))
    assert twin.json()["latestEventSequence"] == seqs[-1]  # snapshot + cursor line up


async def test_projection_drops_internal_payload_fields(h: Harness) -> None:
    await make_events(h)
    path = next(p for p in h.store.paths(f"students/{SID}/events/"))
    doc = h.store.raw(path)
    h.put_doc(path, {**doc, "payload": {**doc["payload"], "outboxId": "x", "modelReasoning": "y"}})
    [first] = (await poll(h, "?after=0&limit=1"))["events"]
    assert first["payload"] == {"taskId": "task_alex_calc_01"}


async def test_expired_and_foreign_cursors(h: Harness) -> None:
    await make_events(h)
    state = f"students/{SID}/eventState/current"
    h.put_doc(state, {**h.store.raw(state), "oldestRetainedSequence": 3})
    r = await h.client.get("/api/events?after=0", headers=h.auth(SID))
    assert r.status_code == 410 and r.json()["error"]["code"] == "EVENT_CURSOR_EXPIRED"
    assert (await poll(h, "?after=2"))["events"][0]["sequence"] == 3  # still valid
    r = await h.client.get("/api/events?after=999", headers=h.auth(SID))
    assert r.status_code == 400  # a cursor this student was never given
    r = await h.client.get("/api/events/stream?after=0", headers=h.auth(SID))
    assert r.status_code == 410  # the stream refuses before it starts


async def test_events_are_isolated_per_student(h: Harness) -> None:
    await make_events(h)
    beth = await poll(h, "?after=0", sid="stu_beth")
    assert beth["events"] == []
    r = await h.client.get("/api/events?after=0&studentId=stu_alex", headers=h.auth("stu_beth"))
    assert r.status_code == 400
    await make_events(h, sid="stu_beth", task="task_beth_calc_01")
    beth = await poll(h, "?after=0", sid="stu_beth")
    assert {e["studentId"] for e in beth["events"]} == {"stu_beth"}
    assert beth["events"][0]["sequence"] == 1  # independent per-student sequence


async def test_sse_replays_heartbeats_and_closes(h: Harness) -> None:
    await make_events(h)
    r = await h.client.get("/api/events/stream?after=1", headers=h.auth(SID))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    frames, comments = parse_sse(r.text)
    assert [int(f["id"]) for f in frames] == [2, 3, 4]
    assert [f["event"] for f in frames] == [f["data"]["type"] for f in frames]
    assert all(f["data"]["studentId"] == SID for f in frames)
    assert "heartbeat" in comments  # sent while idle, within the configured interval
    assert any("reconnect" in c for c in comments)  # closes before the deployment timeout


async def test_sse_last_event_id(h: Harness) -> None:
    await make_events(h)
    r = await h.client.get("/api/events/stream", headers={**h.auth(SID), "Last-Event-ID": "3"})
    frames, _ = parse_sse(r.text)
    assert [int(f["id"]) for f in frames] == [4]
    r = await h.client.get(
        "/api/events/stream?after=1", headers={**h.auth(SID), "Last-Event-ID": "3"}
    )
    assert r.status_code == 400  # inconsistent cursors
    r = await h.client.get("/api/events/stream", headers={**h.auth(SID), "Last-Event-ID": "abc"})
    assert r.status_code == 400


async def test_sse_requires_bearer_auth(h: Harness) -> None:
    r = await h.client.get("/api/events/stream?after=0")
    assert r.status_code == 401
    token = h.auth(SID)["Authorization"].split()[1]
    r = await h.client.get(f"/api/events/stream?after=0&token={token}")
    assert r.status_code == 401  # a token in the URL is never accepted


async def test_sse_closes_when_the_token_expires(clean_env: pytest.MonkeyPatch) -> None:
    h = build_harness(
        clean_env, sse_heartbeat_seconds=0.05, sse_poll_seconds=0.02, sse_max_stream_seconds=30
    )
    await make_events(h)
    from tests.support import emulator_token

    now = h.clock.now()
    token = emulator_token(SID, now=now, exp=int(now.timestamp()) + 1)
    h.clock.advance(seconds=0.9)  # 0.1 s of token life left: the stream must end early
    r = await h.client.get(
        "/api/events/stream?after=0", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    frames, comments = parse_sse(r.text)
    assert len(frames) == 4 and any("reconnect" in c for c in comments)
