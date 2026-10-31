from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class OutboxStatus(StrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"


@dataclass(frozen=True, slots=True, kw_only=True)
class OutboxEntry:
    """Written in the same transaction as the Run it dispatches (CLAUDE.md §2.4)."""

    delivery_id: str
    student_id: str
    run_id: str
    status: OutboxStatus
    created_at: datetime
    dispatched_at: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Delivery:
    """What the queue carries. Contains ids only, never student content."""

    delivery_id: str
    student_id: str
    run_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RunInput:
    """A typed student reply to a Run's input request (e.g. OCR confirmation)."""

    input_request_id: str
    run_id: str
    student_id: str
    confirmed_text: str
    created_at: datetime
