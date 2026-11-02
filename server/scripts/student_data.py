"""Operator tool: per-student backup, restore, consistency check and deletion (Step 31).

Usage (from server/):
  uv run python -m scripts.student_data export  <studentId> <file.json>
  uv run python -m scripts.student_data restore <file.json> [--overwrite]
  uv run python -m scripts.student_data verify  <studentId>
  uv run python -m scripts.student_data delete  <studentId> --confirm <studentId>

Targets the Firestore selected by the environment (emulators locally). Backup files hold
a student's full record: keep them only in the protected backup bucket, never in the repo.
Whole-database backups are Firestore managed backups (doc/OPERATIONS.md); this tool is for
restore drills and deletion requests.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.adapters.firebase import create_async_firestore_client
from app.adapters.firestore.backup import (
    decode_backup,
    delete_student,
    encode_backup,
    export_student,
    restore_student,
    verify_student,
)
from app.adapters.firestore.client_store import FirestoreDocumentStore
from app.config import Settings


async def run(args: argparse.Namespace) -> int:
    store = FirestoreDocumentStore(create_async_firestore_client(Settings()))
    now = datetime.now(UTC)
    if args.cmd == "export":
        backup = await export_student(store, args.student_id, now=now)
        Path(args.file).write_text(encode_backup(backup))
        print(f"exported {len(backup.documents)} documents")
    elif args.cmd == "restore":
        backup = decode_backup(Path(args.file).read_text())
        n = await restore_student(store, backup, overwrite=args.overwrite)
        issues = await verify_student(store, backup.student_id)
        print(f"restored {n} documents; {len(issues)} consistency issues")
        for issue in issues:
            print("  " + issue)
        return 1 if issues else 0
    elif args.cmd == "verify":
        issues = await verify_student(store, args.student_id)
        for issue in issues:
            print(issue)
        print("consistent" if not issues else f"{len(issues)} issues")
        return 1 if issues else 0
    elif args.cmd == "delete":
        if args.confirm != args.student_id:
            print("refusing: pass --confirm with the same student id")
            return 2
        print(f"deleted {await delete_student(store, args.student_id, now=now)} documents")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="student_data")
    sub = parser.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("student_id")
    e.add_argument("file")
    r = sub.add_parser("restore")
    r.add_argument("file")
    r.add_argument("--overwrite", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("student_id")
    d = sub.add_parser("delete")
    d.add_argument("student_id")
    d.add_argument("--confirm", required=True)
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
