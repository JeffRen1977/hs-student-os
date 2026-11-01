"""Durable event feed: polling and SSE over the same sequence cursor (Step 19, API.md §4).

The stream authenticates with `Authorization: Bearer` (browsers use fetch streaming), never
a token in the URL. It replays persisted events after the cursor, then keeps polling the
store, sends heartbeats, and closes before the deployment's request timeout or when the
token expires; the client reconnects with `Last-Event-ID`.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.api import presenters
from app.api.dependencies.auth import Actor, ServicesDep
from app.api.responses import respond
from app.api.routes.params import Limit
from app.bootstrap import Services
from app.domain.errors import DomainError, ErrorCode
from app.domain.event_feed import EventBatch
from app.domain.types.actor import ActorContext
from app.domain.types.common import DEFAULT_PAGE_LIMIT
from app.schemas import event as ev

router = APIRouter(prefix="/api", tags=["events"])

After = Annotated[int | None, Query(ge=0)]


@router.get("/events", response_model=ev.EventPage)
async def list_events(
    actor: Actor, services: ServicesDep, after: After = None, limit: Limit = DEFAULT_PAGE_LIMIT
) -> JSONResponse:
    batch = await services.events.read(actor, after or 0, limit)
    return respond(
        ev.EventPage(
            events=[presenters.event(e) for e in batch.events],
            next_after=batch.next_after,
            has_more=batch.has_more,
        )
    )


def resolve_cursor(after: int | None, last_event_id: str | None) -> int:
    """`Last-Event-ID` wins on reconnect; disagreeing with `after` is a client bug → 400."""
    if last_event_id is None:
        return after or 0
    value = last_event_id.strip()
    if not value.isdigit() or len(value) > 18:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Last-Event-ID must be a sequence number")
    cursor = int(value)
    if after is not None and after != cursor:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Last-Event-ID and after disagree")
    return cursor


def sse_frames(batch: EventBatch) -> list[str]:
    frames = []
    for e in batch.events:
        data = presenters.event(e).model_dump(mode="json", by_alias=True)
        frames.append(
            f"id: {e.sequence}\nevent: {e.type.value}\n"
            f"data: {json.dumps(data, separators=(',', ':'))}\n\n"
        )
    return frames


@router.get("/events/stream")
async def stream_events(
    request: Request,
    actor: Actor,
    services: ServicesDep,
    after: After = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    cursor = resolve_cursor(after, last_event_id)
    # Read once before streaming so 400/410 are real HTTP errors, not mid-stream frames.
    first = await services.events.read(actor, cursor, DEFAULT_PAGE_LIMIT)
    expires_at: datetime | None = getattr(request.state, "token_expires_at", None)
    return StreamingResponse(
        _stream(request, services, actor, first, expires_at),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _stream(
    request: Request,
    services: Services,
    actor: ActorContext,
    first: EventBatch,
    expires_at: datetime | None,
) -> AsyncIterator[str]:
    settings = services.settings
    budget = settings.sse_max_stream_seconds
    if expires_at is not None:
        budget = min(budget, (expires_at - services.clock.now()).total_seconds())
    deadline = time.monotonic() + max(budget, 0.0)
    yield "retry: 3000\n\n"
    batch = first
    last_write = time.monotonic()
    while True:
        for frame in sse_frames(batch):
            yield frame
            last_write = time.monotonic()
        if not batch.has_more:
            if time.monotonic() >= deadline or await request.is_disconnected():
                break
            await asyncio.sleep(min(settings.sse_poll_seconds, max(deadline - time.monotonic(), 0)))
            if time.monotonic() - last_write >= settings.sse_heartbeat_seconds:
                yield ": heartbeat\n\n"
                last_write = time.monotonic()
        try:
            batch = await services.events.read(actor, batch.next_after, DEFAULT_PAGE_LIMIT)
        except DomainError as exc:
            yield f"event: error\ndata: {json.dumps({'code': exc.code.value})}\n\n"
            return
    yield ": stream closing; reconnect with Last-Event-ID\n\n"
