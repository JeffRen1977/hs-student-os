"""Idempotent command handling shared by every POST service (CLAUDE.md §2.6).

Keys are scoped by actor + route scope + client key. The stored record remembers a digest
of the normalized request so a replay with a different body is a conflict, not a replay.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.repositories import Tx
from app.domain.types.actor import ActorContext
from app.domain.types.common import IdempotencyRecord


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandKey:
    scope: str  # e.g. "POST /api/sessions/{sessionId}/submissions"
    key: str  # client Idempotency-Key (already format-validated)
    request_digest: str  # hash of the normalized path + body

    def key_hash(self, actor: ActorContext) -> str:
        raw = f"{actor.actor_id}\n{self.scope}\n{self.key}".encode()
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class Outcome[T]:
    value: T
    replayed: bool = False
    created: bool = True
    delivery_id: str | None = None  # outbox entry to dispatch right after commit


async def find_replay(tx: Tx, actor: ActorContext, cmd: CommandKey) -> IdempotencyRecord | None:
    record = await tx.idempotency.get(actor, cmd.key_hash(actor))
    if record is None:
        return None
    if record.scope != cmd.scope or record.request_digest != cmd.request_digest:
        raise DomainError(
            ErrorCode.IDEMPOTENCY_CONFLICT,
            "This Idempotency-Key was already used with a different request.",
        )
    return record


def remember(
    tx: Tx,
    actor: ActorContext,
    cmd: CommandKey,
    *,
    resource_type: str,
    resource_id: str,
    response_status: int,
    now: datetime,
) -> None:
    tx.idempotency.save(
        actor,
        IdempotencyRecord(
            key_hash=cmd.key_hash(actor),
            scope=cmd.scope,
            request_digest=cmd.request_digest,
            resource_type=resource_type,
            resource_id=resource_id,
            response_status=response_status,
            created_at=now,
        ),
    )
