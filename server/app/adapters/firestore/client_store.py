"""`DocumentStore` over the real Firestore async SDK."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.adapters.firestore.documents import Doc, DocTxn, QuerySpec


def _build_query(base: Any, spec: QuerySpec) -> Any:
    query = base
    for flt in spec.filters:
        query = query.where(filter=FieldFilter(flt.field, flt.op, flt.value))
    for field in spec.order_by:
        query = query.order_by(field)
    if spec.start_after is not None:
        query = query.start_after(dict(zip(spec.order_by, spec.start_after, strict=True)))
    if spec.limit is not None:
        query = query.limit(spec.limit)
    return query


class _TxReader:
    def __init__(self, client: Any, transaction: Any) -> None:
        self._client = client
        self._tx = transaction

    async def get(self, path: str) -> Doc | None:
        snapshot = await self._client.document(path).get(transaction=self._tx)
        return snapshot.to_dict() if snapshot.exists else None

    async def query(self, collection: str, spec: QuerySpec) -> list[Doc]:
        query = _build_query(self._client.collection(collection), spec)
        return [snap.to_dict() async for snap in query.stream(transaction=self._tx)]


class FirestoreDocumentStore:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def run_transaction[T](self, fn: Callable[[DocTxn], Awaitable[T]]) -> T:
        client = self._client

        @firestore.async_transactional
        async def body(transaction: Any) -> T:
            txn = DocTxn(_TxReader(client, transaction))
            result = await fn(txn)
            # All reads are done; flush buffered writes (Firestore: reads before writes).
            for path, write in txn.writes():
                ref = client.document(path)
                if write.kind == "set":
                    transaction.set(ref, write.data)
                else:
                    transaction.update(ref, write.data)
            return result

        result: T = await body(client.transaction())
        return result

    async def query_group(self, collection_id: str, spec: QuerySpec) -> list[Doc]:
        query = _build_query(self._client.collection_group(collection_id), spec)
        return [snap.to_dict() async for snap in query.stream()]
