"""Step 31.4–31.5 against the Firestore emulator: the recursive subtree read, batched
restore and deletion use the real SDK (the in-memory store proves only the logic)."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

from app.adapters.firebase import create_async_firestore_client
from app.adapters.firestore.backup import (
    delete_student,
    export_student,
    restore_student,
    verify_student,
)
from app.adapters.firestore.client_store import FirestoreDocumentStore
from app.adapters.seed_documents import build_seed_documents
from app.config import Settings
from app.registries.fixtures import load_seed_students


async def test_export_delete_restore_round_trip() -> None:
    store = FirestoreDocumentStore(create_async_firestore_client(Settings()))
    now = datetime.now(UTC)
    seed = load_seed_students()[0]
    sid = f"{seed.student.student_id}_{secrets.token_hex(4)}"
    docs = {
        p.replace(seed.student.student_id, sid): {
            **d, **({"studentId": sid} if "studentId" in d else {})
        }
        for p, d in build_seed_documents([seed], now=now).items()
    }  # fmt: skip
    await store.write_documents(docs)
    backup = await export_student(store, sid, now=now)
    assert set(backup.documents) == set(docs)
    assert await verify_student(store, sid) == []
    assert await delete_student(store, sid, now=now) == len(docs)
    assert await store.read_subtree(f"students/{sid}") == {}
    await store.delete_documents([f"deletedStudents/{sid}"])  # drill: lift the tombstone
    assert await restore_student(store, backup) == len(docs)
    assert await verify_student(store, sid) == []
