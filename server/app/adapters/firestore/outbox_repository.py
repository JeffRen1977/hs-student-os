from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.adapters.firestore import paths
from app.adapters.firestore.documents import Doc, DocTxn, Filter, GroupReader, QuerySpec
from app.adapters.firestore.run_repository import run_from_doc
from app.domain.types.actor import ActorContext
from app.domain.types.file import FileStatus, StoredFile
from app.domain.types.outbox import OutboxEntry, OutboxStatus
from app.domain.types.run import Run, RunStatus


def outbox_from_doc(d: Doc) -> OutboxEntry:
    return OutboxEntry(
        delivery_id=d["deliveryId"],
        student_id=d["studentId"],
        run_id=d["runId"],
        status=OutboxStatus(d["status"]),
        created_at=d["createdAt"],
        dispatched_at=d.get("dispatchedAt"),
    )


class FirestoreOutboxStore:
    """`students/{studentId}/outbox/{deliveryId}` — written in the command transaction."""

    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext, delivery_id: str) -> OutboxEntry | None:
        doc = await self._txn.get(paths.sub(actor, "outbox", delivery_id))
        return outbox_from_doc(doc) if doc else None

    def save(self, actor: ActorContext, e: OutboxEntry) -> None:
        if e.student_id != actor.student_id:
            raise ValueError("outbox entry does not belong to actor")
        self._txn.set(
            paths.sub(actor, "outbox", e.delivery_id),
            {
                "deliveryId": e.delivery_id,
                "studentId": e.student_id,
                "runId": e.run_id,
                "status": e.status.value,
                "createdAt": e.created_at,
                "dispatchedAt": e.dispatched_at,
            },
        )


class FirestoreFileStore:
    """File metadata only (`students/{studentId}/files/{fileId}`); uploads land in Step 21."""

    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext, file_id: str) -> StoredFile | None:
        doc = await self._txn.get(paths.sub(actor, "files", file_id))
        if doc is None:
            return None
        return StoredFile(
            file_id=file_id, student_id=actor.student_id, status=FileStatus(doc["status"])
        )


class FirestoreOperationsStore:
    """Collection-group scans used only by service jobs (dispatcher, recovery)."""

    def __init__(self, reader: GroupReader) -> None:
        self._reader = reader

    async def pending_outbox(self, limit: int) -> Sequence[OutboxEntry]:
        docs = await self._reader.query_group(
            "outbox",
            QuerySpec(
                filters=[Filter("status", "==", OutboxStatus.PENDING.value)],
                order_by=("createdAt",),
                limit=limit,
            ),
        )
        return [outbox_from_doc(d) for d in docs]

    async def stalled_runs(
        self, *, queued_before: datetime, lease_expired_before: datetime, limit: int
    ) -> Sequence[Run]:
        queued = await self._reader.query_group(
            "runs",
            QuerySpec(
                filters=[
                    Filter("status", "==", RunStatus.QUEUED.value),
                    Filter("updatedAt", "<=", queued_before),
                ],
                order_by=("updatedAt",),
                limit=limit,
            ),
        )
        running = await self._reader.query_group(
            "runs",
            QuerySpec(
                filters=[
                    Filter("status", "==", RunStatus.RUNNING.value),
                    Filter("leaseExpiresAt", "<=", lease_expired_before),
                ],
                order_by=("leaseExpiresAt",),
                limit=limit,
            ),
        )
        return [run_from_doc(d) for d in queued + running]
