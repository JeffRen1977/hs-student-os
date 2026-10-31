"""Seed the local Firebase emulators with the synthetic fixtures.

Usage (from server/, with emulators running):  uv run python -m scripts.seed_emulator

Refuses to run unless both emulator hosts are set and the project id is `demo-*`, so it
can never write to a real Firebase project.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

from firebase_admin import auth

from app.adapters.firebase import (
    create_sync_firestore_client,
    init_firebase_app,
    resolve_target,
)
from app.adapters.seed_documents import build_seed_documents
from app.config import ConfigError, Settings
from app.registries.content import load_content
from app.registries.fixtures import load_seed_students


def _upsert_auth_user(app: object, uid: str, email: str, display_name: str) -> str:
    try:
        auth.get_user(uid, app=app)
        auth.update_user(uid, email=email, display_name=display_name, app=app)
        return "updated"
    except auth.UserNotFoundError:
        auth.create_user(
            uid=uid, email=email, display_name=display_name, email_verified=True, app=app
        )
        return "created"


def main() -> int:
    settings = Settings()
    target = resolve_target(settings)
    if not target.uses_emulators:
        raise ConfigError(
            "seed_emulator only runs against emulators: set FIRESTORE_EMULATOR_HOST and "
            "FIREBASE_AUTH_EMULATOR_HOST"
        )

    content = load_content()
    seeds = load_seed_students()
    active = content.active_course_ids()
    for seed in seeds:
        for enrollment in seed.student.enrollments:
            if enrollment.course_id not in active:
                raise ConfigError(f"{seed.student.student_id}: {enrollment.course_id} not active")

    app = init_firebase_app(settings)
    db = create_sync_firestore_client(settings)

    for seed in seeds:
        fx = seed.student
        result = _upsert_auth_user(app, fx.student_id, fx.email, fx.profile.display_name)
        print(f"auth user {fx.student_id}: {result}")

    documents = build_seed_documents(seeds, now=datetime.now(UTC))
    batch = db.batch()
    for path, data in documents.items():
        batch.set(db.document(path), data)
    batch.commit()
    print(f"wrote {len(documents)} documents to project {target.project_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
