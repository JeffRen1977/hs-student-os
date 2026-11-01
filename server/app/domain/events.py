"""Publishing domain events that consumers react to (Step 24, BACKEND.md §8).

`EventPublisher.publish` appends the event and, when a registered consumer subscribes to
its type, writes a consumer wake into the outbox *in the same transaction*. The dispatcher
then delivers the wake like a Run delivery; the consumers read the event log from their
own offsets, so a lost or duplicated wake never loses or doubles an effect.

Which event types are consumed is decided by the consumers registered at startup, not by
this module. Consumers act inside one course; no event drives an effect in another course.
"""

from __future__ import annotations

from datetime import datetime

from app.domain.ports.repositories import EventDraft, Tx
from app.domain.types.actor import ActorContext
from app.domain.types.event import DomainEvent, EventType
from app.domain.types.outbox import OutboxEntry, OutboxKind, OutboxStatus


def wake_delivery_id(event_id: str) -> str:
    return f"wake.{event_id}"


class EventPublisher:
    def __init__(self, consumed: frozenset[EventType] = frozenset()) -> None:
        self.consumed = consumed

    async def publish(
        self, tx: Tx, actor: ActorContext, draft: EventDraft, *, event_id: str, now: datetime
    ) -> DomainEvent:
        event = await tx.events.append(actor, draft, event_id=event_id, now=now)
        if event.type in self.consumed:
            tx.outbox.save(
                actor,
                OutboxEntry(
                    delivery_id=wake_delivery_id(event.event_id),
                    student_id=actor.student_id,
                    run_id=None,
                    kind=OutboxKind.CONSUMERS,
                    status=OutboxStatus.PENDING,
                    created_at=now,
                ),
            )
        return event
