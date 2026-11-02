"""Step 5: seeding writes isolated synthetic students into the emulators."""

from __future__ import annotations

from typing import Any

from firebase_admin import auth

from app.adapters.firebase import create_sync_firestore_client, init_firebase_app
from app.config import Settings
from scripts.seed_emulator import main as seed_main


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_seed_is_idempotent_and_isolated() -> None:
    assert seed_main() == 0
    assert seed_main() == 0  # re-running must not fail or duplicate users

    settings = _settings()
    app = init_firebase_app(settings)
    db: Any = create_sync_firestore_client(settings)

    for uid in ("stu_alex", "stu_beth"):
        user = auth.get_user(uid, app=app)
        assert user.email and user.email.endswith("@example.test")

    alex = db.document("students/stu_alex").get().to_dict()
    beth = db.document("students/stu_beth").get().to_dict()
    assert alex["studentId"] == "stu_alex" and beth["studentId"] == "stu_beth"
    assert alex["predictionSummary"]["calc_bc"]["status"] == "unavailable"
    assert "entitlements" not in alex

    assert db.document("students/stu_alex/access/current").get().to_dict()["courses"] == ["dsat"]
    assert db.document("students/stu_beth/access/current").get().to_dict()["courses"] == []

    alex_enrollments = [d.id for d in db.collection("students/stu_alex/enrollments").stream()]
    assert sorted(alex_enrollments) == ["calc_bc", "dsat"]

    # Platform members and the seeded (labelled, not reviewed) Digital SAT package.
    reviewer = db.document("platformMembers/reviewer_platform").get().to_dict()
    assert reviewer["role"] == "platform_reviewer" and reviewer["orgId"] is None
    dsat = db.document("packageVersions/dsat@1.0.0").get().to_dict()
    assert dsat["status"] == "active" and dsat["review"]["reviewerId"] == "seed:local-dev"


def test_firestore_transaction_round_trip() -> None:
    """Sanity check that the emulator gives real transaction semantics."""
    from google.cloud import firestore

    db: Any = create_sync_firestore_client(_settings())
    ref = db.document("students/stu_alex/eventState/current")

    @firestore.transactional
    def bump(tx: Any) -> int:
        current = ref.get(transaction=tx).to_dict()["nextSequence"]
        tx.update(ref, {"nextSequence": current + 1})
        return int(current)

    first = bump(db.transaction())
    second = bump(db.transaction())
    assert second == first + 1
