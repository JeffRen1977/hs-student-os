"""Photo answers: a student uploads a photo of handwritten work and the tutor reads it.

`POST /api/files` stores a validated photo under the student's own record; a message can
attach it by `fileIds`, and the hint run sends it to the model with the student's turn.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from app.domain.ports.llm import LlmRole
from tests.support import Harness, ScriptedProvider, build_harness, idem

SID = "stu_alex"
TASK = "task_alex_calc_01"
# A tiny synthetic JPEG-shaped payload: the server checks the type's magic bytes and size.
JPEG = base64.b64encode(b"\xff\xd8\xff\xe0" + b"synthetic handwriting photo" * 20).decode()
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()


@pytest.fixture
def provider() -> ScriptedProvider:
    return ScriptedProvider()


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch, provider: ScriptedProvider) -> Harness:
    return build_harness(clean_env, llm_provider=provider)


async def upload(
    h: Harness, data: str = JPEG, media_type: str = "image/jpeg", sid: str = SID,
    key: str | None = None,
) -> Any:  # fmt: skip
    return await h.client.post(
        "/api/files",
        json={"mediaType": media_type, "dataBase64": data},
        headers=h.cmd(sid, key),
    )


async def start(h: Harness) -> str:
    r = await h.client.post("/api/sessions", json={"taskId": TASK}, headers=h.cmd(SID))
    assert r.status_code == 201, r.text
    return str(r.json()["sessionId"])


async def test_photo_reaches_the_tutor_model(h: Harness, provider: ScriptedProvider) -> None:
    uploaded = await upload(h)
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["mediaType"] == "image/jpeg" and body["sizeBytes"] > 0
    assert "dataBase64" not in body  # the response never echoes the photo

    session_id = await start(h)
    provider.queue({"reply": "I can read your first two lines. Look at line 3: what is g'(x)?"})
    sent = await h.client.post(
        f"/api/sessions/{session_id}/messages",
        json={"text": "Here is my work.", "fileIds": [body["fileId"]]},
        headers=h.cmd(SID),
    )
    assert sent.status_code == 202, sent.text
    await h.settle()

    [call] = provider.calls
    [turn] = [m for m in call["messages"] if m.role is LlmRole.USER]
    assert turn.text == "Here is my work."
    [image] = turn.images
    assert image.media_type == "image/jpeg" and image.data_base64 == JPEG
    assert "photo of their work" in call["system"]

    r = await h.client.get(f"/api/sessions/{session_id}/messages", headers=h.auth(SID))
    agent = [m for m in r.json()["messages"] if m["role"] == "agent"]
    assert agent and agent[-1]["text"].startswith("I can read your first two lines")


async def test_message_without_photo_sends_text_only(
    h: Harness, provider: ScriptedProvider
) -> None:
    session_id = await start(h)
    provider.queue({"reply": "What is the inner function?"})
    await h.client.post(
        f"/api/sessions/{session_id}/messages", json={"text": "Help?"}, headers=h.cmd(SID)
    )
    await h.settle()
    [call] = provider.calls
    assert all(not m.images for m in call["messages"])


@pytest.mark.parametrize("attach_second_photo", [False, True])
async def test_follow_up_keeps_photos_on_their_original_turns(
    h: Harness, provider: ScriptedProvider, attach_second_photo: bool
) -> None:
    first_file = (await upload(h)).json()["fileId"]
    second_files = []
    if attach_second_photo:
        second_files = [(await upload(h, PNG, "image/png")).json()["fileId"]]
    session_id = await start(h)
    for text, file_ids in [
        ("Here is my work.", [first_file]),
        ("Why is line 3 wrong?", second_files),
    ]:
        provider.queue({"reply": "Check the derivative in line 3."})
        sent = await h.client.post(
            f"/api/sessions/{session_id}/messages",
            json={"text": text, "fileIds": file_ids},
            headers=h.cmd(SID),
        )
        assert sent.status_code == 202, sent.text
        await h.settle()

    assert len(provider.calls) == 2
    turns = provider.calls[-1]["messages"]
    first, follow_up = [m for m in turns if m.role is LlmRole.USER]
    assert first.text == "Here is my work."
    assert [im.data_base64 for im in first.images] == [JPEG]
    assert follow_up.text == "Why is line 3 wrong?"
    assert [im.data_base64 for im in follow_up.images] == ([PNG] if attach_second_photo else [])
    assert all(not m.images for m in turns if m.role is LlmRole.ASSISTANT)


async def test_upload_is_idempotent(h: Harness) -> None:
    key = idem()
    first = await upload(h, key=key)
    replay = await upload(h, key=key)
    assert replay.status_code == 201
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json()["fileId"] == first.json()["fileId"]
    assert len(h.store.paths(f"students/{SID}/files/")) == 1
    conflict = await upload(h, PNG, "image/png", key=key)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_upload_requires_idempotency_key_and_auth(h: Harness) -> None:
    payload = {"mediaType": "image/jpeg", "dataBase64": JPEG}
    no_key = await h.client.post("/api/files", json=payload, headers=h.auth(SID))
    assert no_key.status_code == 400
    no_auth = await h.client.post("/api/files", json=payload, headers={"Idempotency-Key": idem()})
    assert no_auth.status_code == 401


@pytest.mark.parametrize(
    ("data", "media_type"),
    [
        (JPEG, "image/gif"),  # type not allowed
        (PNG, "image/jpeg"),  # content does not match the declared type
        ("not base64!!", "image/jpeg"),
        (base64.b64encode(b"\xff\xd8\xff" + b"0" * 600_001).decode(), "image/jpeg"),  # too big
    ],
)
async def test_invalid_photos_are_rejected(h: Harness, data: str, media_type: str) -> None:
    r = await upload(h, data, media_type)
    assert r.status_code in (400, 422), r.text
    assert h.store.paths(f"students/{SID}/files/") == []


async def test_another_students_photo_cannot_be_attached(h: Harness) -> None:
    other = await upload(h, sid="stu_beth")
    assert other.status_code == 201, other.text
    session_id = await start(h)
    r = await h.client.post(
        f"/api/sessions/{session_id}/messages",
        json={"text": "Here is my work.", "fileIds": [other.json()["fileId"]]},
        headers=h.cmd(SID),
    )
    assert r.status_code == 404
