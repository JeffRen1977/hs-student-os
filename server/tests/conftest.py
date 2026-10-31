from __future__ import annotations

import pytest

_ENV_VARS = (
    "HSOS_APP_ENV",
    "HSOS_GCP_PROJECT_ID",
    "HSOS_LLM_PROVIDER",
    "HSOS_QUEUE_PROVIDER",
    "HSOS_CORS_ALLOWED_ORIGINS",
    "FIRESTORE_EMULATOR_HOST",
    "FIREBASE_AUTH_EMULATOR_HOST",
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Isolate a test from the developer's shell environment and .env file."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir("/")  # no stray .env picked up from the working directory
    return monkeypatch
