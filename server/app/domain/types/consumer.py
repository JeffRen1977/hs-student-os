"""Consumer receipts and offsets (Step 24, BACKEND.md §8).

Course-agnostic: a consumer reacts to events inside one student's log and one course;
the receipt guards its effect so a replayed event can never apply it twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ReceiptOutcome(StrEnum):
    APPLIED = "applied"  # the business effect (event or task) was written
    NO_ACTION = "no_action"  # deliberately nothing; `reason` says why


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsumerReceipt:
    """`(consumerName, eventId, targetSkill)` — written in the same transaction as the
    effect it guards, so a replayed event can never apply it twice (BACKEND.md §8)."""

    consumer: str
    event_id: str
    target_skill_id: str
    outcome: ReceiptOutcome
    reason: str
    created_at: datetime
    task_id: str | None = None
    emitted_event_id: str | None = None

    @property
    def receipt_id(self) -> str:
        return receipt_id_for(self.consumer, self.event_id, self.target_skill_id)


def receipt_id_for(consumer: str, event_id: str, target_skill_id: str) -> str:
    return f"{consumer}:{event_id}:{target_skill_id}"


@dataclass(frozen=True, slots=True, kw_only=True)
class ConsumerOffset:
    """`students/{id}/consumerState/{consumer}`: last event sequence fully handled."""

    consumer: str
    processed_sequence: int
    updated_at: datetime | None = None
