from __future__ import annotations

import pytest

_ENV_VARS = (
    "HSOS_APP_ENV",
    "HSOS_GCP_PROJECT_ID",
    "HSOS_LLM_PROVIDER",
    "HSOS_QUEUE_PROVIDER",
    "HSOS_CORS_ALLOWED_ORIGINS",
    "HSOS_STORAGE_PROVIDER",
    "HSOS_LOCAL_WORKER_ENABLED",
    "HSOS_WORKER_SERVICE_TOKEN",
    "HSOS_WORKER_OIDC_AUDIENCE",
    "HSOS_WORKER_SERVICE_ACCOUNT",
    "HSOS_WORKER_URL",
    "HSOS_LLM_MODEL_FAST",
    "HSOS_LLM_MODEL_BALANCED",
    "HSOS_LLM_MODEL_STRONG",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
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


@pytest.fixture
def harness(clean_env: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    from tests.support import build_harness

    return build_harness(clean_env)
