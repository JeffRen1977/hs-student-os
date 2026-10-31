from __future__ import annotations

import pytest

from app.adapters.firebase import resolve_target
from app.config import ConfigError, Settings


def test_no_emulators_targets_configured_project(clean_env: pytest.MonkeyPatch) -> None:
    target = resolve_target(Settings(_env_file=None, gcp_project_id="demo-x"))  # type: ignore[call-arg]
    assert not target.uses_emulators
    assert target.project_id == "demo-x"


def test_emulator_mode_requires_both_hosts(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    with pytest.raises(ConfigError, match="both"):
        resolve_target(Settings(_env_file=None))  # type: ignore[call-arg]


def test_emulator_mode_requires_demo_project(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    clean_env.setenv("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099")
    with pytest.raises(ConfigError, match="demo-"):
        resolve_target(Settings(_env_file=None, gcp_project_id="real-project"))  # type: ignore[call-arg]


def test_emulator_mode_with_demo_project(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    clean_env.setenv("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099")
    target = resolve_target(Settings(_env_file=None))  # type: ignore[call-arg]
    assert target.uses_emulators
    assert target.project_id.startswith("demo-")
