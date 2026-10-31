from __future__ import annotations

from app.adapters.firestore import paths
from app.adapters.firestore.documents import DocTxn
from app.domain.types.actor import ActorContext
from app.domain.types.common import IdempotencyRecord


class FirestoreIdempotencyStore:
    """`students/{studentId}/idempotency/{keyHash}`. Stores ids and a request digest only —
    never the request body, which may contain student answers."""

    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext, key_hash: str) -> IdempotencyRecord | None:
        doc = await self._txn.get(paths.sub(actor, "idempotency", key_hash))
        if doc is None:
            return None
        return IdempotencyRecord(
            key_hash=doc["keyHash"],
            scope=doc["scope"],
            request_digest=doc["requestDigest"],
            resource_type=doc["resourceType"],
            resource_id=doc["resourceId"],
            response_status=int(doc["responseStatus"]),
            created_at=doc["createdAt"],
        )

    def save(self, actor: ActorContext, r: IdempotencyRecord) -> None:
        self._txn.set(
            paths.sub(actor, "idempotency", r.key_hash),
            {
                "keyHash": r.key_hash,
                "scope": r.scope,
                "requestDigest": r.request_digest,
                "resourceType": r.resource_type,
                "resourceId": r.resource_id,
                "responseStatus": r.response_status,
                "createdAt": r.created_at,
            },
        )
