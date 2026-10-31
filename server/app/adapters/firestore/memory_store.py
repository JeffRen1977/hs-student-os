"""In-process document store with all-or-nothing transactions (tests and local dev only).

Deployed environments refuse `HSOS_STORAGE_PROVIDER=memory` (see `app.config`).
"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from app.adapters.firestore.documents import Doc, DocTxn, Filter, QuerySpec


class SimulatedCommitFailure(RuntimeError):
    """Raised by fault injection to model a transaction that fails at commit."""


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0]


def _matches(doc: Doc, flt: Filter) -> bool:
    if flt.field not in doc:
        return False
    value = doc[flt.field]
    match flt.op:
        case "==":
            return bool(value == flt.value)
        case "in":
            return value in flt.value
        case "<":
            return value is not None and value < flt.value
        case "<=":
            return value is not None and value <= flt.value
        case ">":
            return value is not None and value > flt.value
        case ">=":
            return value is not None and value >= flt.value


def apply_spec(docs: list[Doc], spec: QuerySpec) -> list[Doc]:
    selected = [d for d in docs if all(_matches(d, f) for f in spec.filters)]
    if spec.order_by:
        selected = [d for d in selected if all(f in d for f in spec.order_by)]
        selected.sort(key=lambda d: tuple(d[f] for f in spec.order_by))
        if spec.start_after is not None:
            cursor = tuple(spec.start_after)
            selected = [d for d in selected if tuple(d[f] for f in spec.order_by) > cursor]
    if spec.limit is not None:
        selected = selected[: spec.limit]
    return [copy.deepcopy(d) for d in selected]


class _Reader:
    def __init__(self, data: Mapping[str, Doc]) -> None:
        self._data = data

    async def get(self, path: str) -> Doc | None:
        doc = self._data.get(path)
        return copy.deepcopy(doc) if doc is not None else None

    async def query(self, collection: str, spec: QuerySpec) -> list[Doc]:
        docs = [d for p, d in self._data.items() if _parent(p) == collection]
        return apply_spec(docs, spec)


class MemoryDocumentStore:
    def __init__(self, documents: Mapping[str, Doc] | None = None) -> None:
        self._data: dict[str, Doc] = copy.deepcopy(dict(documents or {}))
        self._lock = asyncio.Lock()
        self.fail_next_commits = 0  # fault injection for crash/rollback tests
        self.commits = 0

    async def run_transaction[T](self, fn: Callable[[DocTxn], Awaitable[T]]) -> T:
        async with self._lock:
            txn = DocTxn(_Reader(self._data))
            result = await fn(txn)
            if self.fail_next_commits > 0:
                self.fail_next_commits -= 1
                raise SimulatedCommitFailure("injected commit failure")
            staged = dict(self._data)
            for path, write in txn.writes():
                if write.kind == "set":
                    staged[path] = copy.deepcopy(write.data)
                elif path in staged:
                    staged[path] = {**staged[path], **copy.deepcopy(write.data)}
                else:
                    raise KeyError(f"update of missing document {path}")
            self._data = staged
            self.commits += 1
            return result

    async def query_group(self, collection_id: str, spec: QuerySpec) -> list[Doc]:
        docs = [d for p, d in self._data.items() if _parent(p).rsplit("/", 1)[-1] == collection_id]
        return apply_spec(docs, spec)

    # Test/diagnostic helpers -----------------------------------------------------------

    def snapshot(self) -> dict[str, Doc]:
        return copy.deepcopy(self._data)

    def put(self, path: str, data: Doc) -> None:
        self._data[path] = copy.deepcopy(data)

    def paths(self, prefix: str = "") -> list[str]:
        return sorted(p for p in self._data if p.startswith(prefix))

    def raw(self, path: str) -> Any:
        return copy.deepcopy(self._data.get(path))
