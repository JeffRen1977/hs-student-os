from __future__ import annotations

from app.adapters.firestore import paths
from app.adapters.firestore.documents import Doc, DocTxn, Filter
from app.adapters.firestore.paging import paged_query
from app.domain.types.actor import ActorContext
from app.domain.types.common import PageRequest, PaginatedResponse
from app.domain.types.message import Message, MessageRole


def message_from_doc(doc: Doc) -> Message:
    return Message(
        message_id=doc["messageId"],
        student_id=doc["studentId"],
        session_id=doc["sessionId"],
        role=MessageRole(doc["role"]),
        text=doc["text"],
        created_at=doc["createdAt"],
        file_ids=tuple(doc.get("fileIds", [])),
        run_id=doc.get("runId"),
        synthetic=bool(doc.get("synthetic", False)),
    )


class FirestoreMessageStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext, message_id: str) -> Message | None:
        doc = await self._txn.get(paths.sub(actor, "messages", message_id))
        return message_from_doc(doc) if doc else None

    async def list_for_session(
        self, actor: ActorContext, session_id: str, page: PageRequest
    ) -> PaginatedResponse[Message]:
        return await paged_query(
            self._txn,
            paths.sub(actor, "messages"),
            filters=[Filter("sessionId", "==", session_id)],
            order_by=("createdAt", "messageId"),
            page=page,
            decode=message_from_doc,
        )

    def save(self, actor: ActorContext, m: Message) -> None:
        if m.student_id != actor.student_id:
            raise ValueError("message does not belong to actor")
        self._txn.set(
            paths.sub(actor, "messages", m.message_id),
            {
                "messageId": m.message_id,
                "studentId": m.student_id,
                "sessionId": m.session_id,
                "role": m.role.value,
                "text": m.text,
                "fileIds": list(m.file_ids),
                "runId": m.run_id,
                "synthetic": m.synthetic,
                "createdAt": m.created_at,
            },
        )
