from __future__ import annotations

from app.adapters.firestore import paths
from app.adapters.firestore.documents import DocTxn, DocumentStore


class FirestoreIdentityDirectory:
    """`identities/{uid}` → `{studentId}`. Students are provisioned by an admin flow; the
    first verified login of a provisioned uid records the mapping. An unknown uid never
    creates a student."""

    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    async def resolve(self, uid: str) -> str | None:
        async def body(txn: DocTxn) -> str | None:
            mapping = await txn.get(paths.identity(uid))
            if mapping is not None:
                return str(mapping["studentId"])
            # Provisioned students use their auth uid as the studentId (see seed script).
            if await txn.get(paths.student(uid)) is None:
                return None
            txn.set(paths.identity(uid), {"uid": uid, "studentId": uid})
            return uid

        return await self._store.run_transaction(body)
