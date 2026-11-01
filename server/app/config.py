"""Environment configuration.

Settings are loaded from environment variables (and an optional local `.env`).
Deployed environments (staging, production) refuse to start with emulator hosts or
mock providers configured, so a misconfigured deploy fails loudly instead of silently
running against fake infrastructure.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.1.0"


class AppEnv(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class LlmProvider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    MOCK = "mock"


# Default tier → model ids per real provider. Override with HSOS_LLM_MODEL_{FAST,BALANCED,STRONG}.
DEFAULT_MODELS: dict[LlmProvider, tuple[str, str, str]] = {
    LlmProvider.ANTHROPIC: ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"),
    LlmProvider.OPENAI: ("gpt-5.4-mini", "gpt-5.4", "gpt-5.5"),
}


class QueueProvider(StrEnum):
    CLOUD_TASKS = "cloud_tasks"
    LOCAL = "local"


class StorageProvider(StrEnum):
    FIRESTORE = "firestore"
    MEMORY = "memory"  # in-process store for local dev and deterministic tests only


DEPLOYED_ENVS = frozenset({AppEnv.STAGING, AppEnv.PRODUCTION})


class ConfigError(ValueError):
    """Raised when the configuration is unsafe for the selected environment."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HSOS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    app_env: AppEnv = AppEnv.LOCAL
    gcp_project_id: str = "demo-hs-student-os"
    api_port: int = Field(default=8787, ge=1, le=65535)
    llm_provider: LlmProvider = LlmProvider.MOCK
    queue_provider: QueueProvider = QueueProvider.LOCAL
    storage_provider: StorageProvider = StorageProvider.FIRESTORE
    cors_allowed_origins: list[str] = Field(default_factory=list)

    # Run execution (Step 15).
    run_lease_seconds: int = Field(default=120, ge=10, le=3600)
    run_max_attempts: int = Field(default=3, ge=1, le=10)
    # QUEUED runs untouched for this long are assumed to have lost their delivery.
    run_requeue_after_seconds: int = Field(default=300, ge=30, le=86_400)
    # Local only: run the outbox dispatcher + worker loop inside the API process.
    local_worker_enabled: bool = True
    local_worker_poll_seconds: float = Field(default=1.0, gt=0, le=60)

    # Model gateway (Step 16). Tier → model id; unset tiers use DEFAULT_MODELS for the
    # selected provider. Keys come from ANTHROPIC_API_KEY / OPENAI_API_KEY (Secret Manager
    # when deployed); SecretStr keeps them out of reprs and logs.
    llm_model_fast: str | None = None
    llm_model_balanced: str | None = None
    llm_model_strong: str | None = None
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=600)
    llm_max_attempts: int = Field(default=3, ge=1, le=5)
    llm_run_token_budget: int = Field(default=40_000, ge=1_000)
    llm_session_token_budget: int = Field(default=200_000, ge=1_000)
    llm_daily_token_budget: int = Field(default=400_000, ge=1_000)
    # Production refuses to serve content that has not passed human review.
    require_reviewed_content: bool = False

    # Event stream (Step 19). Close before Cloud Run's request timeout; clients reconnect.
    sse_heartbeat_seconds: float = Field(default=15.0, gt=0, le=60)
    sse_poll_seconds: float = Field(default=1.0, gt=0, le=30)
    sse_max_stream_seconds: float = Field(default=300.0, gt=0, le=3000)

    # Worker authentication. Locally a shared service token; deployed, Google OIDC.
    worker_service_token: SecretStr | None = None
    worker_oidc_audience: str | None = None
    worker_service_account: str | None = None
    worker_url: str | None = None
    cloud_tasks_location: str | None = None
    cloud_tasks_queue: str | None = None

    # Google SDKs read these exact (unprefixed) variable names, so we read them too.
    firestore_emulator_host: str | None = Field(
        default=None, validation_alias="FIRESTORE_EMULATOR_HOST"
    )
    firebase_auth_emulator_host: str | None = Field(
        default=None, validation_alias="FIREBASE_AUTH_EMULATOR_HOST"
    )

    @property
    def is_deployed(self) -> bool:
        return self.app_env in DEPLOYED_ENVS

    def llm_models(self) -> tuple[str, str, str]:
        """(fast, balanced, strong) model ids for the selected provider."""
        fast, balanced, strong = DEFAULT_MODELS.get(
            self.llm_provider, DEFAULT_MODELS[LlmProvider.ANTHROPIC]
        )
        return (
            self.llm_model_fast or fast,
            self.llm_model_balanced or balanced,
            self.llm_model_strong or strong,
        )

    @property
    def uses_emulators(self) -> bool:
        return bool(self.firestore_emulator_host or self.firebase_auth_emulator_host)

    @model_validator(mode="after")
    def _reject_unsafe_deployed_config(self) -> Settings:
        if not self.is_deployed:
            return self
        problems: list[str] = []
        if self.firestore_emulator_host:
            problems.append("FIRESTORE_EMULATOR_HOST is set")
        if self.firebase_auth_emulator_host:
            problems.append("FIREBASE_AUTH_EMULATOR_HOST is set")
        if self.llm_provider is LlmProvider.MOCK:
            problems.append("HSOS_LLM_PROVIDER=mock")
        if self.queue_provider is QueueProvider.LOCAL:
            problems.append("HSOS_QUEUE_PROVIDER=local")
        if self.storage_provider is StorageProvider.MEMORY:
            problems.append("HSOS_STORAGE_PROVIDER=memory")
        if self.worker_service_token is not None:
            problems.append("HSOS_WORKER_SERVICE_TOKEN is local-only (use OIDC)")
        if not (self.worker_oidc_audience and self.worker_service_account):
            problems.append(
                "HSOS_WORKER_OIDC_AUDIENCE and HSOS_WORKER_SERVICE_ACCOUNT are required"
            )
        if self.app_env is AppEnv.PRODUCTION and not self.require_reviewed_content:
            problems.append("HSOS_REQUIRE_REVIEWED_CONTENT must be true in production")
        if self.gcp_project_id.startswith("demo-"):
            problems.append("HSOS_GCP_PROJECT_ID is an emulator-only demo project")
        if problems:
            raise ConfigError(f"Refusing to start in {self.app_env.value}: " + "; ".join(problems))
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
