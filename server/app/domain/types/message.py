from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class MessageRole(StrEnum):
    STUDENT = "student"
    AGENT = "agent"


@dataclass(frozen=True, slots=True, kw_only=True)
class Message:
    """One turn of a per-course agent conversation, persisted in order."""

    message_id: str
    student_id: str
    session_id: str
    role: MessageRole
    text: str
    created_at: datetime
    file_ids: Sequence[str] = ()
    run_id: str | None = None
    # True when produced by synthetic execution: never real tutoring or grading.
    synthetic: bool = False
