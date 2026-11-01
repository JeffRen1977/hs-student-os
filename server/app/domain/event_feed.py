"""Durable per-student event feed shared by polling and SSE (Step 19, BACKEND.md §8).

Persisted events are the source of truth; there is no in-process pub/sub. Any API
instance can serve any reconnect, because a cursor is just a per-student sequence.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.repositories import Tx, UnitOfWork
from app.domain.types.actor import ActorContext, Permission
from app.domain.types.event import DomainEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class EventBatch:
    events: Sequence[DomainEvent]
    next_after: int
    has_more: bool
    latest_sequence: int


class EventFeedService:
    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def read(self, actor: ActorContext, after: int, limit: int) -> EventBatch:
        actor.require(Permission.LEARNING_READ)
        if after < 0 or not 1 <= limit <= 100:
            raise DomainError(ErrorCode.VALIDATION_FAILED, "invalid event cursor or limit")

        async def body(tx: Tx) -> EventBatch:
            oldest = await tx.events.oldest_retained_sequence(actor)
            if after < oldest - 1:
                raise DomainError(
                    ErrorCode.EVENT_CURSOR_EXPIRED,
                    "Events after this cursor were purged; reload state and resubscribe.",
                )
            latest = await tx.events.latest_sequence(actor)
            if after > latest:
                # Not a cursor this student was ever given (e.g. from another account).
                raise DomainError(ErrorCode.VALIDATION_FAILED, "cursor is ahead of the feed")
            events = list(await tx.events.list_after(actor, after, limit + 1))
            has_more = len(events) > limit
            events = events[:limit]
            return EventBatch(
                events=events,
                next_after=events[-1].sequence if events else after,
                has_more=has_more,
                latest_sequence=latest,
            )

        return await self._uow.transaction(body)
