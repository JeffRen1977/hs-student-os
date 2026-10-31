"""The narrow document-access seam every repository is written against.

Repositories in this package are written once, against `DocTxn`. Two backends provide it:

- `FirestoreDocumentStore` — the real Firestore SDK (emulator locally, Cloud Firestore
  deployed). This is the production path and is exercised by `tests/emulator/`.
- `MemoryDocumentStore` — an in-process store for deterministic tests and local runs
  without Java. It applies a transaction's writes all-or-nothing and supports fault
  injection, but it is *not* evidence that a real Firestore transaction behaves the same.

`DocTxn` buffers writes until commit and lets later reads in the same transaction see
them (Firestore itself requires reads before writes; buffering keeps that rule out of the
domain code). Queries do not see the transaction's own buffered writes.
"""

from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

Doc = dict[str, Any]
Op = Literal["==", "in", "<", "<=", ">", ">="]


@dataclass(frozen=True, slots=True)
class Filter:
    field: str
    op: Op
    value: Any


@dataclass(frozen=True, slots=True, kw_only=True)
class QuerySpec:
    """Equality/range filters, ascending order, optional keyset cursor and limit."""

    filters: Sequence[Filter] = ()
    order_by: Sequence[str] = ()
    start_after: Sequence[Any] | None = None  # values for `order_by`, in order
    limit: int | None = None


class DocReader(Protocol):
    async def get(self, path: str) -> Doc | None: ...

    async def query(self, collection: str, spec: QuerySpec) -> list[Doc]: ...


class GroupReader(Protocol):
    async def query_group(self, collection_id: str, spec: QuerySpec) -> list[Doc]:
        """Collection-group query across all students. Service-only callers."""
        ...


@dataclass(slots=True)
class _Write:
    kind: Literal["set", "update"]
    data: Doc


class DocTxn:
    def __init__(self, reader: DocReader) -> None:
        self._reader = reader
        self._writes: dict[str, list[_Write]] = {}

    async def get(self, path: str) -> Doc | None:
        pending = self._writes.get(path)
        base: Doc | None
        if pending and pending[0].kind == "set":
            base = None
        else:
            base = await self._reader.get(path)
        for write in pending or ():
            if write.kind == "set":
                base = copy.deepcopy(write.data)
            elif base is not None:
                base.update(copy.deepcopy(write.data))
        return base

    async def query(self, collection: str, spec: QuerySpec) -> list[Doc]:
        return await self._reader.query(collection, spec)

    def set(self, path: str, data: Doc) -> None:
        """Replace the whole document."""
        self._writes[path] = [_Write("set", copy.deepcopy(data))]

    def update(self, path: str, fields: Doc) -> None:
        """Replace the given top-level fields of an existing document."""
        self._writes.setdefault(path, []).append(_Write("update", copy.deepcopy(fields)))

    def writes(self) -> list[tuple[str, _Write]]:
        """One collapsed write per document (a commit writes each document at most once)."""
        collapsed: list[tuple[str, _Write]] = []
        for path, ws in self._writes.items():
            kind = ws[0].kind
            data: Doc = {}
            for w in ws:
                data = copy.deepcopy(w.data) if w.kind == "set" else {**data, **w.data}
            collapsed.append((path, _Write(kind, data)))
        return collapsed


class DocumentStore(GroupReader, Protocol):
    async def run_transaction[T](self, fn: Callable[[DocTxn], Awaitable[T]]) -> T: ...
