from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.adapters.firestore import paths
from app.adapters.firestore.documents import Doc, DocTxn, Filter, QuerySpec
from app.domain.ports.repositories import EventDraft
from app.domain.types.actor import ActorContext
from app.domain.types.event import CURRENT_EVENT_SCHEMA_VERSION, DomainEvent, EventType


def event_from_doc(d: Doc) -> DomainEvent:
    return DomainEvent(
        event_id=d["eventId"],
        sequence=int(d["sequence"]),
        schema_version=int(d["schemaVersion"]),
        student_id=d["studentId"],
        type=EventType(d["type"]),
        occurred_at=d["occurredAt"],
        causation_id=d.get("causationId"),
        session_id=d.get("sessionId"),
        run_id=d.get("runId"),
        payload=dict(d.get("payload", {})),
    )


class FirestoreEventStore:
    """Per-student monotonic sequence held in `eventState/current`.

    Reading and writing the counter inside the command's transaction makes concurrent
    appends for one student conflict, so sequences are gap-free and never duplicated.
    """

    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def append(
        self, actor: ActorContext, draft: EventDraft, *, event_id: str, now: datetime
    ) -> DomainEvent:
        state_path = paths.sub(actor, "eventState", "current")
        state = await self._txn.get(state_path)
        sequence = int(state["nextSequence"]) if state else 1
        self._txn.set(state_path, {"nextSequence": sequence + 1})
        event = DomainEvent(
            event_id=event_id,
            sequence=sequence,
            schema_version=CURRENT_EVENT_SCHEMA_VERSION,
            student_id=actor.student_id,
            type=draft.type,
            occurred_at=now,
            causation_id=draft.causation_id,
            session_id=draft.session_id,
            run_id=draft.run_id,
            payload=dict(draft.payload or {}),
        )
        self._txn.set(
            paths.sub(actor, "events", event_id),
            {
                "eventId": event.event_id,
                "sequence": event.sequence,
                "schemaVersion": event.schema_version,
                "studentId": event.student_id,
                "type": event.type.value,
                "occurredAt": event.occurred_at,
                "causationId": event.causation_id,
                "sessionId": event.session_id,
                "runId": event.run_id,
                "payload": dict(event.payload),
            },
        )
        return event

    async def latest_sequence(self, actor: ActorContext) -> int:
        state = await self._txn.get(paths.sub(actor, "eventState", "current"))
        return int(state["nextSequence"]) - 1 if state else 0

    async def list_after(
        self, actor: ActorContext, after_sequence: int, limit: int
    ) -> Sequence[DomainEvent]:
        docs = await self._txn.query(
            paths.sub(actor, "events"),
            QuerySpec(
                filters=[Filter("sequence", ">", after_sequence)],
                order_by=("sequence",),
                limit=limit,
            ),
        )
        return [event_from_doc(d) for d in docs]
