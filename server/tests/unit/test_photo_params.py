"""Photos are sent to the model as image blocks before the student's text."""

from __future__ import annotations

from datetime import UTC, datetime

from app.adapters.llm.anthropic_provider import message_param
from app.adapters.llm.gateway import IMAGE_TOKENS
from app.adapters.llm.openai_provider import input_param
from app.domain.context_loader import conversation, conversation_messages
from app.domain.ports.llm import LlmImage, LlmMessage, LlmRole
from app.domain.types.file import ImageContent
from app.domain.types.message import Message, MessageRole

PHOTO = LlmImage(media_type="image/png", data_base64="iVBORw0KGgo=")


def test_anthropic_user_turn_with_photo() -> None:
    param = message_param(LlmMessage(role=LlmRole.USER, text="my work", images=(PHOTO,)))
    assert param["role"] == "user"
    image, text = list(param["content"])
    assert image == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="},
    }
    assert text == {"type": "text", "text": "my work"}


def test_anthropic_text_only_turns_are_unchanged() -> None:
    assert message_param(LlmMessage(role=LlmRole.USER, text="hi")) == {
        "role": "user",
        "content": "hi",
    }
    assert message_param(LlmMessage(role=LlmRole.ASSISTANT, text="ok")) == {
        "role": "assistant",
        "content": "ok",
    }


def test_openai_user_turn_with_photo() -> None:
    param = input_param(LlmMessage(role=LlmRole.USER, text="my work", images=(PHOTO,)))
    image, text = param["content"]
    assert image == {"type": "input_image", "image_url": "data:image/png;base64,iVBORw0KGgo="}
    assert text == {"type": "input_text", "text": "my work"}


def test_photos_count_toward_the_token_estimate() -> None:
    assert IMAGE_TOKENS >= 1_000


def test_history_truncation_counts_photos_and_preserves_turn_association() -> None:
    photo = ImageContent(media_type=PHOTO.media_type, data_base64=PHOTO.data_base64)
    messages = [
        Message(
            message_id=f"m{i}",
            student_id="s",
            session_id="session",
            role=MessageRole.STUDENT,
            text="My work",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            file_ids=(f"file{i}",),
        )
        for i in range(3)
    ]
    images = {f"file{i}": photo for i in range(3)}
    budget = IMAGE_TOKENS * 2 + 20
    assert [m.message_id for m in conversation_messages(messages, budget)] == ["m1", "m2"]
    turns = conversation(messages, budget, images)
    assert len(turns) == 2
    assert all(list(m.images) == [PHOTO] for m in turns)


def test_truncated_photo_is_not_moved_to_a_later_text_turn() -> None:
    messages = [
        Message(
            message_id="photo",
            student_id="s",
            session_id="session",
            role=MessageRole.STUDENT,
            text="My work",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            file_ids=("file",),
        ),
        Message(
            message_id="follow_up",
            student_id="s",
            session_id="session",
            role=MessageRole.STUDENT,
            text="Why?",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    ]
    turns = conversation(
        messages,
        IMAGE_TOKENS,
        {"file": ImageContent(media_type=PHOTO.media_type, data_base64=PHOTO.data_base64)},
    )
    assert len(turns) == 1 and turns[0].text == "Why?"
    assert not turns[0].images
