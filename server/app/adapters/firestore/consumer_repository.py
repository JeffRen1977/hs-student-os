"""Consumer receipts and offsets (Step 24).

- `students/{id}/consumerReceipts/{consumer}:{eventId}:{target}`
- `students/{id}/consumerState/{consumer}` — processed event sequence
"""

from __future__ import annotations

from app.adapters.firestore import paths
from app.adapters.firestore.documents import DocTxn
from app.domain.types.actor import ActorContext
from app.domain.types.consumer import ConsumerOffset, ConsumerReceipt, ReceiptOutcome


class FirestoreReceiptStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext, receipt_id: str) -> ConsumerReceipt | None:
        d = await self._txn.get(paths.sub(actor, "consumerReceipts", receipt_id))
        if d is None:
            return None
        return ConsumerReceipt(
            consumer=d["consumer"],
            event_id=d["eventId"],
            target_skill_id=d["targetSkillId"],
            outcome=ReceiptOutcome(d["outcome"]),
            reason=d["reason"],
            created_at=d["createdAt"],
            task_id=d.get("taskId"),
            emitted_event_id=d.get("emittedEventId"),
        )

    def create(self, actor: ActorContext, r: ConsumerReceipt) -> None:
        self._txn.set(
            paths.sub(actor, "consumerReceipts", r.receipt_id),
            {
                "receiptId": r.receipt_id,
                "consumer": r.consumer,
                "eventId": r.event_id,
                "targetSkillId": r.target_skill_id,
                "outcome": r.outcome.value,
                "reason": r.reason,
                "createdAt": r.created_at,
                "taskId": r.task_id,
                "emittedEventId": r.emitted_event_id,
            },
        )


class FirestoreConsumerOffsetStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext, consumer: str) -> ConsumerOffset | None:
        d = await self._txn.get(paths.sub(actor, "consumerState", consumer))
        if d is None:
            return None
        return ConsumerOffset(
            consumer=d["consumer"],
            processed_sequence=int(d["processedSequence"]),
            updated_at=d.get("updatedAt"),
        )

    def save(self, actor: ActorContext, o: ConsumerOffset) -> None:
        self._txn.set(
            paths.sub(actor, "consumerState", o.consumer),
            {
                "consumer": o.consumer,
                "processedSequence": o.processed_sequence,
                "updatedAt": o.updated_at,
            },
        )
