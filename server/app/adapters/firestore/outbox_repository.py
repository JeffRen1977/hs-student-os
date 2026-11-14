from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.adapters.firestore import paths
from app.adapters.firestore.documents import Doc, DocTxn, Filter, GroupReader, QuerySpec
from app.adapters.firestore.run_repository import run_from_doc
from app.domain.types.actor import ActorContext
from app.domain.types.file import FileStatus, ImageContent, StoredFile
from app.domain.types.outbox import OutboxEntry, OutboxKind, OutboxStatus
from app.domain.types.run import Run, RunStatus


def outbox_from_doc(d: Doc) -> OutboxEntry:
    return OutboxEntry(
        delivery_id=d["deliveryId"],
        student_id=d["studentId"],
        run_id=d.get("runId"),
        status=OutboxStatus(d["status"]),
        created_at=d["createdAt"],
        dispatched_at=d.get("dispatchedAt"),
        kind=OutboxKind(d.get("kind", OutboxKind.RUN.value)),
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
                "kind": e.kind.value,
                "status": e.status.value,
                "createdAt": e.created_at,
                "dispatchedAt": e.dispatched_at,
            },
        )


class FirestoreFileStore:
    """`students/{studentId}/files/{fileId}`. Photo answers keep their (size-capped, base64)
    bytes in the same document until Cloud Storage uploads exist (Step 21)."""

    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext, file_id: str) -> StoredFile | None:
        doc = await self._txn.get(paths.sub(actor, "files", file_id))
        if doc is None:
            return None
        return StoredFile(
            file_id=file_id,
            student_id=actor.student_id,
            status=FileStatus(doc["status"]),
            media_type=doc.get("mediaType", ""),
            size_bytes=doc.get("sizeBytes", 0),
        )

    async def get_image(self, actor: ActorContext, file_id: str) -> ImageContent | None:
        doc = await self._txn.get(paths.sub(actor, "files", file_id))
        if doc is None or not doc.get("dataBase64"):
            return None
        return ImageContent(media_type=doc["mediaType"], data_base64=doc["dataBase64"])

    def save_image(
        self, actor: ActorContext, file: StoredFile, image: ImageContent, *, now: datetime
    ) -> None:
        self._txn.set(
            paths.sub(actor, "files", file.file_id),
            {
                "fileId": file.file_id,
                "studentId": actor.student_id,
                "status": file.status.value,
                "mediaType": image.media_type,
                "sizeBytes": file.size_bytes,
                "dataBase64": image.data_base64,
                "createdAt": now,
            },
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

    async def stalled_consumer_wakes(
        self, *, dispatched_before: datetime, limit: int
    ) -> Sequence[OutboxEntry]:
        docs = await self._reader.query_group(
            "outbox",
            QuerySpec(
                filters=[
                    Filter("kind", "==", OutboxKind.CONSUMERS.value),
                    Filter("status", "==", OutboxStatus.DISPATCHED.value),
                    Filter("dispatchedAt", "<=", dispatched_before),
                ],
                order_by=("dispatchedAt",),
                limit=limit,
            ),
        )
        return [outbox_from_doc(d) for d in docs]

    async def due_plan_schedules(self, *, due_before: datetime, limit: int) -> Sequence[str]:
        docs = await self._reader.query_group(
            "planState",
            QuerySpec(
                filters=[Filter("nextDueAt", "<=", due_before)],
                order_by=("nextDueAt",),
                limit=limit,
            ),
        )
        return [str(d["studentId"]) for d in docs if d.get("studentId")]

    async def due_reminders(
        self, *, due_before: datetime, claim_expired_before: datetime, limit: int
    ) -> Sequence[tuple[str, str]]:
        pending = await self._reader.query_group(
            "reminders",
            QuerySpec(
                filters=[
                    Filter("status", "==", "pending"),
                    Filter("sendAt", "<=", due_before),
                ],
                order_by=("sendAt",),
                limit=limit,
            ),
        )
        stuck = await self._reader.query_group(
            "reminders",
            QuerySpec(
                filters=[
                    Filter("status", "==", "sending"),
                    Filter("claimedAt", "<=", claim_expired_before),
                ],
                order_by=("claimedAt",),
                limit=limit,
            ),
        )
        return [(str(d["studentId"]), str(d["reminderId"])) for d in pending + stuck]

    async def failed_runs_since(self, *, since: datetime, limit: int) -> Sequence[Run]:
        docs = await self._reader.query_group(
            "runs",
            QuerySpec(
                filters=[
                    Filter("status", "==", RunStatus.FAILED.value),
                    Filter("updatedAt", ">=", since),
                ],
                order_by=("updatedAt",),
                limit=limit,
            ),
        )
        return [run_from_doc(d) for d in docs]

    async def student_ids(self, *, after: str | None, limit: int) -> Sequence[str]:
        docs = await self._reader.query_group(
            "students",
            QuerySpec(
                order_by=("studentId",),
                start_after=(after,) if after is not None else None,
                limit=limit,
            ),
        )
        return [str(d["studentId"]) for d in docs]
