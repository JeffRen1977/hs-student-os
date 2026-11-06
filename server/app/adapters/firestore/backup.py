"""Per-student backup, restore, consistency check and deletion (Steps 31.4–31.5).

Production backups are Firestore managed backups/exports of the whole database (see
`deploy/` and doc/OPERATIONS.md); this module is the per-student path used to prove a
restore is *consistent* — every link inside a student's record resolves — and to delete a
student completely. It runs as an operator job (`scripts/student_data.py`), never from the
student API.

- `export_student` → every document under `students/{id}` plus the `identities/{uid}`
  mappings to that student. Datetimes are tagged so the JSON round-trips exactly.
- `restore_student` → writes a backup into a (separate) store. It refuses a student that
  has been deleted (tombstone `deletedStudents/{id}`), so restoring an older backup never
  resurrects deleted data, and refuses to overwrite an existing student unless asked.
- `verify_student` → the list of broken links (empty means consistent).
- `delete_student` → removes the subtree, identity mappings and the parent-link index
  entries and invites the student's links point to, and writes a tombstone
  holding only the id and time. Collection-group scans (outbox, runs, plan schedules,
  reminders) then find nothing for the student; managed backups that still contain the
  student expire with the backup retention period. Aggregate course metrics
  (`courseMetrics/{courseId}`, Step 34.4) hold no student data and are left as they are.
- A restore brings back a student's parent links but not the parent's index entry, so a
  restored link grants nothing until the parent is linked again.

Uploaded files (Cloud Storage objects) are not built yet (text-only pilot); when they
are, their objects must be exported and deleted alongside `students/{id}/files`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.adapters.firestore.documents import Doc, DocTxn, Filter, QuerySpec

BACKUP_FORMAT = "hsos-student-backup/v1"
TOMBSTONES = "deletedStudents"


class SubtreeStore(Protocol):
    async def run_transaction[T](self, fn: Any) -> T: ...

    async def read_subtree(self, root: str) -> dict[str, Doc]: ...

    async def write_documents(self, docs: Mapping[str, Doc]) -> None: ...

    async def delete_documents(self, doc_paths: Sequence[str]) -> None: ...


class RestoreRefused(RuntimeError):
    pass


@dataclass(frozen=True, slots=True, kw_only=True)
class StudentBackup:
    student_id: str
    exported_at: datetime
    documents: Mapping[str, Doc]


async def _identity_docs(store: SubtreeStore, student_id: str) -> dict[str, Doc]:
    async def read(txn: DocTxn) -> list[Doc]:
        return await txn.query(
            "identities", QuerySpec(filters=[Filter("studentId", "==", student_id)])
        )

    docs: list[Doc] = await store.run_transaction(read)
    return {f"identities/{d['uid']}": d for d in docs if d.get("uid")}


async def export_student(store: SubtreeStore, student_id: str, *, now: datetime) -> StudentBackup:
    docs = await store.read_subtree(f"students/{student_id}")
    if f"students/{student_id}" not in docs:
        raise LookupError("student not found")
    docs.update(await _identity_docs(store, student_id))
    return StudentBackup(student_id=student_id, exported_at=now, documents=docs)


async def restore_student(
    store: SubtreeStore, backup: StudentBackup, *, overwrite: bool = False
) -> int:
    sid = backup.student_id
    for path in backup.documents:
        if not (path == f"students/{sid}" or path.startswith(f"students/{sid}/")) and not (
            path.startswith("identities/") and backup.documents[path].get("studentId") == sid
        ):
            raise RestoreRefused(f"document outside the student's record: {path}")
    if await store.read_subtree(f"{TOMBSTONES}/{sid}"):
        raise RestoreRefused("student was deleted; deleted data is never restored")
    if not overwrite and await store.read_subtree(f"students/{sid}"):
        raise RestoreRefused("student already exists in the target store")
    await store.write_documents(backup.documents)
    return len(backup.documents)


def _parent_link_paths(docs: Mapping[str, Doc], student_id: str) -> list[str]:
    """Documents outside the subtree that a student's parent links point to (Step 36): the
    parent's index entry and the invite. Derived from the links themselves."""
    prefix = f"students/{student_id}/parentLinks/"
    out: list[str] = []
    for path, d in docs.items():
        if not path.startswith(prefix):
            continue
        if d.get("parentUid"):
            out.append(f"parents/{d['parentUid']}/children/{student_id}")
        if d.get("inviteCodeHash"):
            out.append(f"parentInvites/{d['inviteCodeHash']}")
    return out


async def delete_student(store: SubtreeStore, student_id: str, *, now: datetime) -> int:
    docs = await store.read_subtree(f"students/{student_id}")
    linked = _parent_link_paths(docs, student_id)
    docs.update(await _identity_docs(store, student_id))
    # Children first, so an interrupted run never leaves an orphaned subtree without its
    # root (a re-run finishes the job).
    ordered = sorted(docs, key=lambda p: p.count("/"), reverse=True)
    # Parent access goes first: once the links are gone nothing else points here.
    await store.delete_documents(linked)
    await store.delete_documents(ordered)
    await store.write_documents(
        {f"{TOMBSTONES}/{student_id}": {"studentId": student_id, "deletedAt": now}}
    )
    return len(ordered)


# ---- Consistency ---------------------------------------------------------------------


def _children(docs: Mapping[str, Doc], base: str, coll: str) -> dict[str, Doc]:
    prefix = f"{base}/{coll}/"
    return {
        p[len(prefix) :]: d
        for p, d in docs.items()
        if p.startswith(prefix) and "/" not in p[len(prefix) :]
    }


async def verify_student(store: SubtreeStore, student_id: str) -> list[str]:
    """Broken links inside one student's record. Empty list = consistent."""
    base = f"students/{student_id}"
    docs = await store.read_subtree(base)
    issues: list[str] = []
    if base not in docs:
        return ["student document missing"]
    tasks = _children(docs, base, "tasks")
    sessions = _children(docs, base, "sessions")
    runs = _children(docs, base, "runs")
    subs = _children(docs, base, "submissions")
    assessments = _children(docs, base, "assessments")
    plans = _children(docs, base, "plans")
    outbox = _children(docs, base, "outbox")

    def need(cond: bool, what: str) -> None:
        if not cond:
            issues.append(what)

    for path, d in docs.items():
        sid = d.get("studentId")
        if sid is not None and sid != student_id and path != base:
            issues.append(f"{path}: belongs to another student")
    for sid_, s in sessions.items():
        need(s.get("taskId") in tasks, f"sessions/{sid_}: task {s.get('taskId')} missing")
        active = s.get("activeRunId")
        need(active is None or active in runs, f"sessions/{sid_}: active run missing")
    for tid, t in tasks.items():
        open_s = t.get("openSessionId")
        need(open_s is None or open_s in sessions, f"tasks/{tid}: open session missing")
    for rid, r in runs.items():
        sess = r.get("sessionId")
        need(sess is None or sess in sessions, f"runs/{rid}: session missing")
        result = r.get("result") or {}
        for key, coll in (("assessmentId", assessments), ("planId", plans)):
            ref = result.get(key)
            need(ref is None or ref in coll, f"runs/{rid}: result {key} missing")
    for sub_id, s in subs.items():
        need(s.get("sessionId") in sessions, f"submissions/{sub_id}: session missing")
        need(s.get("runId") in runs, f"submissions/{sub_id}: run missing")
    for aid, a in assessments.items():
        need(a.get("sessionId") in sessions, f"assessments/{aid}: session missing")
        need(a.get("runId") in runs, f"assessments/{aid}: run missing")
        need(a.get("submissionId") in subs, f"assessments/{aid}: submission missing")
    for oid, o in outbox.items():
        need(o.get("runId") is None or o["runId"] in runs, f"outbox/{oid}: run missing")
    state = docs.get(f"{base}/planState/current") or {}
    latest = state.get("latestPlanId")
    need(latest is None or latest in plans, "planState: latest plan missing")
    event_state = docs.get(f"{base}/eventState/current") or {"nextSequence": 1}
    seqs = sorted(int(e["sequence"]) for e in _children(docs, base, "events").values())
    expected = list(
        range(int(event_state.get("oldestRetainedSequence", 1)), int(event_state["nextSequence"]))
    )
    need(seqs == expected, "events: sequence has gaps or does not match eventState")
    return issues


# ---- JSON encoding (datetimes round-trip exactly) -----------------------------------


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_encode(v) for v in value]
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"__datetime__"}:
            return datetime.fromisoformat(value["__datetime__"])
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def encode_backup(b: StudentBackup) -> str:
    return json.dumps(
        {
            "format": BACKUP_FORMAT,
            "studentId": b.student_id,
            "exportedAt": b.exported_at.isoformat(),
            "documents": _encode(dict(b.documents)),
        },
        sort_keys=True,
    )


def decode_backup(text: str) -> StudentBackup:
    raw = json.loads(text)
    if raw.get("format") != BACKUP_FORMAT:
        raise ValueError("not a student backup")
    return StudentBackup(
        student_id=raw["studentId"],
        exported_at=datetime.fromisoformat(raw["exportedAt"]),
        documents=_decode(raw["documents"]),
    )
