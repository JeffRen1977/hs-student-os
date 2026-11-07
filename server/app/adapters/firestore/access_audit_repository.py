"""`students/{studentId}/accessAudit/{auditId}`: course access changes (Step 42).

Written in the same transaction as `access/current`. Only admin actors (holding
`entitlements:manage`) read or write it; no student API returns it.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.adapters.firestore import paths
from app.adapters.firestore.documents import Doc, DocTxn, QuerySpec
from app.domain.types.access import AccessAuditEntry, AccessChange
from app.domain.types.actor import ActorContext, Permission

COLLECTION = "accessAudit"


def _require_admin(actor: ActorContext) -> None:
    if not actor.can(Permission.ENTITLEMENTS_MANAGE):
        raise PermissionError("the access audit is for entitlements:manage only")


def to_doc(e: AccessAuditEntry) -> Doc:
    return {
        "auditId": e.audit_id,
        "studentId": e.student_id,
        "courseId": e.course_id,
        "change": e.change.value,
        "reason": e.reason,
        "actorId": e.actor_id,
        "at": e.at,
    }


def from_doc(d: Doc) -> AccessAuditEntry:
    return AccessAuditEntry(
        audit_id=d["auditId"],
        student_id=d["studentId"],
        course_id=d["courseId"],
        change=AccessChange(d["change"]),
        reason=d["reason"],
        actor_id=d["actorId"],
        at=d["at"],
    )


class FirestoreAccessAuditStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    def append(self, actor: ActorContext, entry: AccessAuditEntry) -> None:
        _require_admin(actor)
        if entry.student_id != actor.student_id:
            raise ValueError("audit entry does not belong to actor's student")
        self._txn.set(paths.sub(actor, COLLECTION, entry.audit_id), to_doc(entry))

    async def list_recent(self, actor: ActorContext, limit: int) -> Sequence[AccessAuditEntry]:
        _require_admin(actor)
        docs = await self._txn.query(paths.sub(actor, COLLECTION), QuerySpec(order_by=("at",)))
        return [from_doc(d) for d in reversed(docs)][:limit]
