"""Shared consumer pieces: the handler protocol and receipts (Step 24).

Consumers are course-internal: an effect is only ever applied in the course the event
belongs to.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.domain.ports.repositories import Tx
from app.domain.types.actor import ActorContext
from app.domain.types.consumer import ConsumerReceipt, ReceiptOutcome, receipt_id_for
from app.domain.types.event import DomainEvent, EventType


class Consumer(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def subscribes(self) -> frozenset[EventType]: ...

    async def handle(self, tx: Tx, actor: ActorContext, event: DomainEvent, now: datetime) -> None:
        """Apply this event's effect *inside* `tx`, guarded by a receipt. Must not call
        external services; the transaction may be retried."""
        ...


async def has_receipt(
    tx: Tx, actor: ActorContext, consumer: str, event_id: str, target_skill_id: str
) -> bool:
    return (
        await tx.receipts.get(actor, receipt_id_for(consumer, event_id, target_skill_id))
        is not None
    )


def write_receipt(
    tx: Tx,
    actor: ActorContext,
    *,
    consumer: str,
    event: DomainEvent,
    target_skill_id: str,
    outcome: ReceiptOutcome,
    reason: str,
    now: datetime,
    task_id: str | None = None,
    emitted_event_id: str | None = None,
) -> None:
    tx.receipts.create(
        actor,
        ConsumerReceipt(
            consumer=consumer,
            event_id=event.event_id,
            target_skill_id=target_skill_id,
            outcome=outcome,
            reason=reason,
            created_at=now,
            task_id=task_id,
            emitted_event_id=emitted_event_id,
        ),
    )
