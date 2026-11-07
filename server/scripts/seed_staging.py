"""Seed a dedicated staging project with the synthetic fixtures. Never real student data.

Usage (from server/, with Application Default Credentials for the staging project):
    HSOS_STAGING_TEST_PASSWORD='<choose one>' uv run python -m scripts.seed_staging \\
        --project hs-student-os --confirm hs-student-os

This writes to a real Firebase project, so it refuses unless:
- the emulator hosts are unset and the project id is given twice (--project/--confirm);
- the project is not `demo-*` (use `seed_emulator` for the emulators);
- the database holds no student other than the synthetic fixtures, so it can never be
  pointed at a project that has real students;
- HSOS_STAGING_TEST_PASSWORD is set. Fixture users get that password so a smoke test can
  sign in; it is never printed or committed.

Seeded packages carry the same audit note as the local seed ("not a platform review").
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime

from firebase_admin import auth

from app.adapters.firebase import create_sync_firestore_client, init_firebase_app
from app.adapters.seed_documents import build_platform_documents, build_seed_documents
from app.config import ConfigError, Settings
from app.registries.fixtures import load_platform_fixture, load_seed_students

PASSWORD_ENV = "HSOS_STAGING_TEST_PASSWORD"
EMULATOR_ENV = ("FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST")


def check_target(project: str, confirm: str, env: Mapping[str, str]) -> str:
    """The password, once the target is confirmed to be a real, explicitly named project."""
    if project != confirm:
        raise ConfigError("--project and --confirm must name the same project")
    if project.startswith("demo-"):
        raise ConfigError("demo-* projects are emulator-only: use scripts.seed_emulator")
    if set_hosts := [name for name in EMULATOR_ENV if env.get(name)]:
        raise ConfigError(f"unset {', '.join(set_hosts)}: this script targets a real project")
    password = env.get(PASSWORD_ENV, "")
    if len(password) < 12:
        raise ConfigError(f"set {PASSWORD_ENV} (at least 12 characters)")
    return password


#: Counters and schedules the runtime owns once a student exists. Re-seeding must not reset
#: them: a reset `nextSequence` reissues sequence numbers that existing events already hold,
#: and consumers whose `processedSequence` is past the reset silently skip the new events.
RUNTIME_STATE_SUFFIXES = ("/eventState/current", "/planState/current")


def without_existing_runtime_state[D](
    documents: Mapping[str, D], existing: Iterable[str]
) -> tuple[dict[str, D], set[str]]:
    """The documents to write, minus runtime state already in the database (and which)."""
    kept = {p for p in existing if p in documents and p.endswith(RUNTIME_STATE_SUFFIXES)}
    return {p: d for p, d in documents.items() if p not in kept}, kept


def foreign_students(existing: Iterable[str], synthetic: Iterable[str]) -> list[str]:
    """Students in the database that are not fixtures: any one of them stops the seed."""
    return sorted(set(existing) - set(synthetic))


def _upsert_auth_user(app: object, uid: str, email: str, display_name: str, password: str) -> str:
    try:
        auth.get_user(uid, app=app)
        auth.update_user(uid, email=email, display_name=display_name, password=password, app=app)
        return "updated"
    except auth.UserNotFoundError:
        auth.create_user(
            uid=uid, email=email, display_name=display_name, password=password,
            email_verified=True, app=app,
        )  # fmt: skip
        return "created"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args(argv)
    password = check_target(args.project, args.confirm, os.environ)

    settings = Settings(_env_file=None, gcp_project_id=args.project)
    seeds = load_seed_students()
    platform = load_platform_fixture()  # fixture schemas reject anything not synthetic

    db = create_sync_firestore_client(settings)
    existing = [ref.id for ref in db.collection("students").list_documents()]
    if foreign := foreign_students(existing, (s.student.student_id for s in seeds)):
        raise ConfigError(
            f"refusing: {len(foreign)} non-fixture student(s) already in {args.project}"
        )

    app = init_firebase_app(settings)
    for seed in seeds:
        fx = seed.student
        result = _upsert_auth_user(app, fx.student_id, fx.email, fx.profile.display_name, password)
        print(f"auth user {fx.student_id}: {result}")
    for member in platform.members:
        result = _upsert_auth_user(app, member.uid, member.email, member.display_name, password)
        print(f"auth user {member.uid} ({member.role}): {result}")
    for parent in platform.parents:
        result = _upsert_auth_user(app, parent.uid, parent.email, parent.display_name, password)
        print(f"auth user {parent.uid} (parent): {result}")

    now = datetime.now(UTC)
    documents = {
        **build_seed_documents(seeds, now=now),
        **build_platform_documents(platform, now=now),
    }
    candidates = [p for p in documents if p.endswith(RUNTIME_STATE_SUFFIXES)]
    existing_state = {s.reference.path for s in db.get_all([db.document(p) for p in candidates])
                      if s.exists}  # fmt: skip
    documents, kept = without_existing_runtime_state(documents, existing_state)
    batch = db.batch()
    for path, data in documents.items():
        batch.set(db.document(path), data)
    batch.commit()
    print(f"wrote {len(documents)} synthetic documents to project {args.project}")
    if kept:
        print(f"kept {len(kept)} existing runtime-state documents: {', '.join(sorted(kept))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
