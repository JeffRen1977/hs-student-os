from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    configured = os.environ.get("FIRESTORE_EMULATOR_HOST") and os.environ.get(
        "FIREBASE_AUTH_EMULATOR_HOST"
    )
    skip = pytest.mark.skip(reason="Firebase emulators not configured (run `make test-emulator`)")
    for item in items:
        if "tests/emulator" in str(item.fspath):
            item.add_marker(pytest.mark.emulator)
            if not configured:
                item.add_marker(skip)
