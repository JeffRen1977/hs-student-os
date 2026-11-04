"""The DocTxn seam and the in-memory backend's all-or-nothing semantics."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from google.api_core.exceptions import Aborted

from app.adapters.firestore.client_store import retry_on_contention
from app.adapters.firestore.documents import DocTxn, Filter, QuerySpec
from app.adapters.firestore.memory_store import MemoryDocumentStore, SimulatedCommitFailure
from app.adapters.firestore.paging import decode_cursor, encode_cursor
from app.domain.errors import DomainError, ErrorCode


async def test_exception_in_transaction_writes_nothing() -> None:
    store = MemoryDocumentStore({"c/a": {"n": 1}})

    async def body(txn: DocTxn) -> None:
        txn.set("c/b", {"n": 2})
        txn.update("c/a", {"n": 99})
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await store.run_transaction(body)
    assert store.snapshot() == {"c/a": {"n": 1}}


async def test_commit_failure_writes_nothing() -> None:
    store = MemoryDocumentStore()
    store.fail_next_commits = 1

    async def body(txn: DocTxn) -> None:
        txn.set("c/a", {"n": 1})

    with pytest.raises(SimulatedCommitFailure):
        await store.run_transaction(body)
    assert store.snapshot() == {}
    await store.run_transaction(body)
    assert store.snapshot() == {"c/a": {"n": 1}}


async def test_reads_see_own_buffered_writes() -> None:
    store = MemoryDocumentStore({"c/a": {"n": 1, "keep": True}})

    async def body(txn: DocTxn) -> tuple[object, object]:
        txn.update("c/a", {"n": 2})
        txn.update("c/a", {"n": 3})
        txn.set("c/b", {"x": 1})
        return await txn.get("c/a"), await txn.get("c/b")

    a, b = await store.run_transaction(body)
    assert a == {"n": 3, "keep": True} and b == {"x": 1}
    assert store.raw("c/a") == {"n": 3, "keep": True}


async def test_query_filters_order_cursor_and_groups() -> None:
    t = datetime(2026, 1, 1, tzinfo=UTC)
    store = MemoryDocumentStore(
        {
            "students/a/tasks/t1": {"id": "t1", "d": "2026-01-02", "s": "P"},
            "students/a/tasks/t2": {"id": "t2", "d": "2026-01-01", "s": "P"},
            "students/a/tasks/t3": {"id": "t3", "d": "2026-01-01", "s": "X"},
            "students/b/tasks/t4": {"id": "t4", "d": "2026-01-01", "s": "P"},
            "students/b/outbox/o1": {"id": "o1", "at": t},
        }
    )

    async def body(txn: DocTxn) -> list[str]:
        docs = await txn.query(
            "students/a/tasks",
            QuerySpec(
                filters=[Filter("s", "in", ["P"])],
                order_by=("d", "id"),
                start_after=("2026-01-01", "t2"),
            ),
        )
        return [d["id"] for d in docs]

    assert await store.run_transaction(body) == ["t1"]  # other students never leak in
    group = await store.query_group(
        "tasks", QuerySpec(filters=[Filter("d", "<=", "2026-01-01")], order_by=("id",))
    )
    assert [d["id"] for d in group] == ["t2", "t3", "t4"]


def test_cursor_round_trip_and_rejects_garbage() -> None:
    t = datetime(2026, 1, 1, 12, tzinfo=UTC)
    assert decode_cursor(encode_cursor(["a", 3, t]), 3) == ["a", 3, t]
    for bad in ("@@@", encode_cursor(["only-one"])):
        with pytest.raises(DomainError):
            decode_cursor(bad, 2)


def test_outbox_documents_written_before_m3_still_load() -> None:
    from datetime import UTC, datetime

    from app.adapters.firestore.outbox_repository import outbox_from_doc
    from app.domain.types.outbox import OutboxKind

    entry = outbox_from_doc(
        {
            "deliveryId": "run_1.g1",
            "studentId": "stu_alex",
            "runId": "run_1",
            "status": "pending",
            "createdAt": datetime(2026, 11, 1, tzinfo=UTC),
        }
    )
    assert entry.kind is OutboxKind.RUN and entry.run_id == "run_1"


async def _no_sleep(_: float) -> None:
    return None


async def test_contention_retries_whole_transaction_then_succeeds() -> None:
    calls = 0

    async def attempt() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise Aborted("Transaction lock timeout.")  # a read aborted
        if calls == 2:
            raise ValueError("Failed to commit transaction in 5 attempts.") from Aborted("x")
        return "ok"

    assert await retry_on_contention(attempt, sleep=_no_sleep) == "ok"
    assert calls == 3


async def test_persistent_contention_is_a_retryable_503_not_a_500() -> None:
    async def attempt() -> None:
        raise Aborted("Transaction lock timeout.")

    with pytest.raises(DomainError) as err:
        await retry_on_contention(attempt, attempts=3, sleep=_no_sleep)
    assert err.value.code is ErrorCode.SERVICE_UNAVAILABLE and err.value.retryable


async def test_non_contention_errors_are_not_retried() -> None:
    calls = 0

    async def attempt() -> None:
        nonlocal calls
        calls += 1
        raise ValueError("message does not belong to actor")

    with pytest.raises(ValueError):
        await retry_on_contention(attempt, sleep=_no_sleep)
    assert calls == 1
