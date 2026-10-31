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
    MOCK = "mock"


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
        if self.gcp_project_id.startswith("demo-"):
            problems.append("HSOS_GCP_PROJECT_ID is an emulator-only demo project")
        if problems:
            raise ConfigError(f"Refusing to start in {self.app_env.value}: " + "; ".join(problems))
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
