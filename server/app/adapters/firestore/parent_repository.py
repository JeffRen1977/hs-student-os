"""Parent links (Step 36, BACKEND.md §3).

    students/{studentId}/parentLinks/{linkId}      the authoritative link + granted scopes
    parentInvites/{codeHash}                       one-time invite → (studentId, linkId)
    parents/{uid}                                  provisioned parent identity
    parents/{uid}/children/{studentId}             the parent's index (re-checked on read)
    parents/{uid}/idempotency/{keyHash}            the parent's command replay records

Invite codes are stored only as SHA-256 hashes.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.adapters.firestore import paths
from app.adapters.firestore.documents import Doc, DocTxn, DocumentStore, QuerySpec
from app.domain.types.actor import ActorContext
from app.domain.types.common import IdempotencyRecord
from app.domain.types.parent import ParentChild, ParentInvite, ParentLink, ParentLinkStatus

LINKS = "parentLinks"
LINK_LIMIT = 20
CHILD_LIMIT = 20


def _id(value: str) -> str:
    if not value or "/" in value:
        raise ValueError("invalid document id")
    return value


def parent_path(uid: str) -> str:
    return f"parents/{_id(uid)}"


def invite_path(code_hash: str) -> str:
    return f"parentInvites/{_id(code_hash)}"


def link_to_doc(link: ParentLink) -> Doc:
    return {
        "linkId": link.link_id,
        "studentId": link.student_id,
        "status": link.status.value,
        "scopes": list(link.scopes),
        "inviteCodeHash": link.invite_code_hash,
        "inviteExpiresAt": link.invite_expires_at,
        "createdAt": link.created_at,
        "parentUid": link.parent_uid,
        "parentDisplayName": link.parent_display_name,
        "acceptedAt": link.accepted_at,
        "revokedAt": link.revoked_at,
        "version": link.version,
    }


def link_from_doc(d: Doc) -> ParentLink:
    return ParentLink(
        link_id=d["linkId"],
        student_id=d["studentId"],
        status=ParentLinkStatus(d["status"]),
        scopes=tuple(d.get("scopes", ())),
        invite_code_hash=d["inviteCodeHash"],
        invite_expires_at=d["inviteExpiresAt"],
        created_at=d["createdAt"],
        parent_uid=d.get("parentUid"),
        parent_display_name=d.get("parentDisplayName"),
        accepted_at=d.get("acceptedAt"),
        revoked_at=d.get("revokedAt"),
        version=int(d.get("version", 1)),
    )


def _record_from_doc(doc: Doc) -> IdempotencyRecord:
    return IdempotencyRecord(
        key_hash=doc["keyHash"],
        scope=doc["scope"],
        request_digest=doc["requestDigest"],
        resource_type=doc["resourceType"],
        resource_id=doc["resourceId"],
        response_status=int(doc["responseStatus"]),
        created_at=doc["createdAt"],
    )


class FirestoreParentStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get_link(self, actor: ActorContext, link_id: str) -> ParentLink | None:
        doc = await self._txn.get(paths.sub(actor, LINKS, link_id))
        return link_from_doc(doc) if doc else None

    async def list_links(self, actor: ActorContext) -> Sequence[ParentLink]:
        docs = await self._txn.query(
            paths.sub(actor, LINKS), QuerySpec(order_by=("createdAt",), limit=LINK_LIMIT)
        )
        return [link_from_doc(d) for d in docs]

    def save_link(self, actor: ActorContext, link: ParentLink) -> None:
        if link.student_id != actor.student_id:
            raise ValueError("link does not belong to actor")
        self._txn.set(paths.sub(actor, LINKS, link.link_id), link_to_doc(link))

    async def get_invite(self, code_hash: str) -> ParentInvite | None:
        d = await self._txn.get(invite_path(code_hash))
        if d is None:
            return None
        return ParentInvite(
            code_hash=d["codeHash"],
            student_id=d["studentId"],
            link_id=d["linkId"],
            expires_at=d["expiresAt"],
            redeemed_by=d.get("redeemedBy"),
        )

    def save_invite(self, invite: ParentInvite) -> None:
        self._txn.set(
            invite_path(invite.code_hash),
            {
                "codeHash": invite.code_hash,
                "studentId": invite.student_id,
                "linkId": invite.link_id,
                "expiresAt": invite.expires_at,
                "redeemedBy": invite.redeemed_by,
            },
        )

    async def get_child(self, parent_uid: str, student_id: str) -> ParentChild | None:
        d = await self._txn.get(f"{parent_path(parent_uid)}/children/{_id(student_id)}")
        if d is None:
            return None
        return ParentChild(
            student_id=d["studentId"], link_id=d["linkId"], created_at=d["createdAt"]
        )

    async def list_children(self, parent_uid: str) -> Sequence[ParentChild]:
        docs = await self._txn.query(
            f"{parent_path(parent_uid)}/children",
            QuerySpec(order_by=("studentId",), limit=CHILD_LIMIT),
        )
        return [
            ParentChild(student_id=d["studentId"], link_id=d["linkId"], created_at=d["createdAt"])
            for d in docs
        ]

    def save_child(self, parent_uid: str, child: ParentChild) -> None:
        self._txn.set(
            f"{parent_path(parent_uid)}/children/{_id(child.student_id)}",
            {"studentId": child.student_id, "linkId": child.link_id, "createdAt": child.created_at},
        )

    def delete_child(self, parent_uid: str, student_id: str) -> None:
        self._txn.delete(f"{parent_path(parent_uid)}/children/{_id(student_id)}")

    async def get_parent_idempotency(
        self, parent_uid: str, key_hash: str
    ) -> IdempotencyRecord | None:
        doc = await self._txn.get(f"{parent_path(parent_uid)}/idempotency/{_id(key_hash)}")
        return _record_from_doc(doc) if doc else None

    def save_parent_idempotency(self, parent_uid: str, r: IdempotencyRecord) -> None:
        self._txn.set(
            f"{parent_path(parent_uid)}/idempotency/{_id(r.key_hash)}",
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


class FirestoreParentDirectory:
    """`parents/{uid}`: provisioned parent accounts (seed fixtures locally). A uid not
    listed is not a parent, whatever its token says."""

    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    async def resolve(self, uid: str) -> str | None:
        """The parent's display name, or None when the uid is not a parent."""

        async def body(txn: DocTxn) -> Doc | None:
            return await txn.get(parent_path(uid))

        doc = await self._store.run_transaction(body)
        if doc is None or doc.get("role") != "parent":
            return None
        return str(doc.get("displayName") or "Parent")
