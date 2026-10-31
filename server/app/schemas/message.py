from __future__ import annotations

from app.domain.types.message import MessageRole
from app.schemas.common import ApiModel, OpaqueId, UtcDatetime


class Message(ApiModel):
    message_id: OpaqueId
    session_id: OpaqueId
    role: MessageRole
    text: str
    file_ids: list[OpaqueId]
    run_id: OpaqueId | None
    created_at: UtcDatetime
    # True for synthetic-execution output: a pipeline test, not tutoring or grading.
    synthetic: bool


class MessageList(ApiModel):
    messages: list[Message]
    next_cursor: str | None
