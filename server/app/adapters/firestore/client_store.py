"""`DocumentStore` over the real Firestore async SDK."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from google.api_core.exceptions import Aborted
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.adapters.firestore.documents import Doc, DocTxn, QuerySpec
from app.domain.errors import DomainError, ErrorCode

# Whole-transaction attempts when Firestore aborts for contention. The SDK already retries
# an aborted *commit* (keeping its place in line); it does not retry a read that aborts,
# and when its own attempts run out it raises a bare ValueError.
CONTENTION_ATTEMPTS = 4
CONTENTION_BACKOFF_SECONDS = 0.05


def is_contention(exc: BaseException) -> bool:
    if isinstance(exc, Aborted):
        return True
    # The SDK wraps a commit that aborted on every attempt: ValueError from Aborted.
    return isinstance(exc, ValueError) and isinstance(exc.__cause__, Aborted)


async def retry_on_contention[T](
    attempt: Callable[[], Awaitable[T]],
    *,
    attempts: int = CONTENTION_ATTEMPTS,
    backoff_seconds: float = CONTENTION_BACKOFF_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Re-run a whole transaction on contention with jittered exponential backoff, so two
    requests racing for the same document stop retrying in lockstep. Transaction bodies
    are retry-safe: writes are buffered and no external calls happen inside (CLAUDE.md
    §2.4). Persistent contention is a typed, retryable 503, never a 500."""
    last: BaseException | None = None
    for n in range(attempts):
        if n:
            await sleep(random.uniform(0, backoff_seconds * 2**n))
        try:
            return await attempt()
        except Exception as exc:
            if not is_contention(exc):
                raise
            last = exc
    raise DomainError(
        ErrorCode.SERVICE_UNAVAILABLE, "The service is busy. Try again.", retryable=True
    ) from last


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
                if write.kind == "delete":
                    transaction.delete(ref)
                elif write.kind == "set":
                    transaction.set(ref, write.data)
                else:
                    transaction.update(ref, write.data)
            return result

        return await retry_on_contention(lambda: body(client.transaction()))

    async def query_group(self, collection_id: str, spec: QuerySpec) -> list[Doc]:
        query = _build_query(self._client.collection_group(collection_id), spec)
        return [snap.to_dict() async for snap in query.stream()]

    # Backup / restore / deletion (Step 31.4–31.5). Not transactional: these run as
    # operator jobs on a quiesced student (see doc/OPERATIONS.md).

    async def read_subtree(self, root: str) -> dict[str, Doc]:
        out: dict[str, Doc] = {}

        async def walk(doc_ref: Any) -> None:
            snap = await doc_ref.get()
            if snap.exists:
                out[doc_ref.path] = snap.to_dict()
            async for coll in doc_ref.collections():
                async for child in coll.list_documents():
                    await walk(child)

        await walk(self._client.document(root))
        return out

    async def write_documents(self, docs: Mapping[str, Doc]) -> None:
        items = list(docs.items())
        for i in range(0, len(items), 400):
            batch = self._client.batch()
            for path, doc in items[i : i + 400]:
                batch.set(self._client.document(path), doc)
            await batch.commit()

    async def delete_documents(self, doc_paths: Sequence[str]) -> None:
        for i in range(0, len(doc_paths), 400):
            batch = self._client.batch()
            for path in doc_paths[i : i + 400]:
                batch.delete(self._client.document(path))
            await batch.commit()
