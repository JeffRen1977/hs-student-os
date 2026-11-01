from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import AppEnv, LlmProvider, QueueProvider, Settings, StorageProvider
from app.main import create_app

SAFE_PROD = {
    "app_env": AppEnv.PRODUCTION,
    "gcp_project_id": "hs-student-os-prod",
    "llm_provider": LlmProvider.ANTHROPIC,
    "queue_provider": QueueProvider.CLOUD_TASKS,
    "storage_provider": StorageProvider.FIRESTORE,
    "worker_oidc_audience": "https://worker.example.test",
    "worker_service_account": "tasks-invoker@hs-student-os-prod.iam.gserviceaccount.com",
    "require_reviewed_content": True,
}


def make(clean_env: pytest.MonkeyPatch, **overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def test_local_defaults_allow_emulators_and_mocks(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    clean_env.setenv("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099")
    settings = make(clean_env)
    assert settings.app_env is AppEnv.LOCAL
    assert settings.uses_emulators
    assert settings.llm_provider is LlmProvider.MOCK


def test_safe_production_config_is_accepted(clean_env: pytest.MonkeyPatch) -> None:
    settings = make(clean_env, **SAFE_PROD)
    assert settings.is_deployed
    assert not settings.uses_emulators


@pytest.mark.parametrize("env", [AppEnv.PRODUCTION, AppEnv.STAGING])
@pytest.mark.parametrize("var", ["FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST"])
def test_deployed_envs_reject_emulator_hosts(
    clean_env: pytest.MonkeyPatch, env: AppEnv, var: str
) -> None:
    clean_env.setenv(var, "127.0.0.1:1234")
    with pytest.raises(ValidationError, match=var):
        make(clean_env, **{**SAFE_PROD, "app_env": env})


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"llm_provider": LlmProvider.MOCK}, "HSOS_LLM_PROVIDER=mock"),
        ({"queue_provider": QueueProvider.LOCAL}, "HSOS_QUEUE_PROVIDER=local"),
        ({"gcp_project_id": "demo-hs-student-os"}, "demo project"),
        ({"storage_provider": StorageProvider.MEMORY}, "HSOS_STORAGE_PROVIDER=memory"),
        ({"worker_service_token": "local-secret"}, "HSOS_WORKER_SERVICE_TOKEN"),
        ({"worker_oidc_audience": None}, "HSOS_WORKER_OIDC_AUDIENCE"),
    ],
)
def test_production_rejects_mock_providers(
    clean_env: pytest.MonkeyPatch, override: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        make(clean_env, **{**SAFE_PROD, **override})


def test_production_startup_aborts_with_emulator_env(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("HSOS_APP_ENV", "production")
    clean_env.setenv("HSOS_GCP_PROJECT_ID", "hs-student-os-prod")
    clean_env.setenv("HSOS_LLM_PROVIDER", "anthropic")
    clean_env.setenv("HSOS_QUEUE_PROVIDER", "cloud_tasks")
    clean_env.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    with pytest.raises(ValidationError):
        create_app(Settings(_env_file=None))  # type: ignore[call-arg]


def test_production_hides_api_docs(clean_env: pytest.MonkeyPatch) -> None:
    app = create_app(make(clean_env, **SAFE_PROD))
    assert app.openapi_url is None
    assert app.docs_url is None


def test_production_requires_reviewed_content(clean_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="REQUIRE_REVIEWED_CONTENT"):
        make(clean_env, **{**SAFE_PROD, "require_reviewed_content": False})


def test_model_defaults_follow_the_selected_provider(clean_env: pytest.MonkeyPatch) -> None:
    assert make(clean_env, llm_provider=LlmProvider.ANTHROPIC).llm_models() == (
        "claude-haiku-5-5",
        "claude-sonnet-5-5",
        "claude-opus-5-5",
    )
    assert make(clean_env, llm_provider=LlmProvider.OPENAI).llm_models() == (
        "gpt-5.4-mini",
        "gpt-5.4",
        "gpt-5.5",
    )
    custom = make(clean_env, llm_provider=LlmProvider.OPENAI, llm_model_strong="gpt-5.5-pro")
    assert custom.llm_models()[2] == "gpt-5.5-pro"


def test_api_keys_are_secret_and_read_from_unprefixed_vars(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    settings = make(clean_env, llm_provider=LlmProvider.OPENAI)
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "sk-test-not-a-real-key"
    assert "sk-test" not in repr(settings)


def test_openai_is_accepted_as_a_production_provider(clean_env: pytest.MonkeyPatch) -> None:
    assert make(clean_env, **{**SAFE_PROD, "llm_provider": LlmProvider.OPENAI}).is_deployed
