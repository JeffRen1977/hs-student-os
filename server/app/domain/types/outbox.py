from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class OutboxStatus(StrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"  # consumer wakes only: the consumers caught up past it


class OutboxKind(StrEnum):
    RUN = "run"  # execute one Run
    CONSUMERS = "consumers"  # wake the student's domain event consumers


@dataclass(frozen=True, slots=True, kw_only=True)
class OutboxEntry:
    """Written in the same transaction as the Run it dispatches, or as the event that
    consumers must react to (CLAUDE.md §2.4)."""

    delivery_id: str
    student_id: str
    run_id: str | None
    status: OutboxStatus
    created_at: datetime
    dispatched_at: datetime | None = None
    kind: OutboxKind = OutboxKind.RUN

    def __post_init__(self) -> None:
        if (self.kind is OutboxKind.RUN) != (self.run_id is not None):
            raise ValueError("run deliveries (and only they) carry a run_id")


@dataclass(frozen=True, slots=True, kw_only=True)
class Delivery:
    """What the queue carries. Contains ids only, never student content."""

    delivery_id: str
    student_id: str
    run_id: str | None
    kind: OutboxKind = OutboxKind.RUN


@dataclass(frozen=True, slots=True, kw_only=True)
class RunInput:
    """A typed student reply to a Run's input request (e.g. OCR confirmation)."""

    input_request_id: str
    run_id: str
    student_id: str
    confirmed_text: str
    created_at: datetime
