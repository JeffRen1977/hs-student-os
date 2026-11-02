"""Step 30: the staging env files (deploy/staging/*.env.yaml) start the real config.

provision.sh adds the project, URLs and service accounts; the Anthropic key comes from
Secret Manager. This proves the checked-in settings pass the deployed-environment checks
(no emulators or mocks, OIDC worker auth, JSON logs, a lease longer than a model call).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import AppEnv, ReminderProvider, Settings

DEPLOY = Path(__file__).resolve().parents[3] / "deploy" / "staging"
INJECTED = {
    "HSOS_GCP_PROJECT_ID": "hsos-staging-example",
    "HSOS_WORKER_URL": "https://hsos-worker-abc.run.app",
    "HSOS_WORKER_OIDC_AUDIENCE": "https://hsos-worker-abc.run.app",
    "HSOS_WORKER_SERVICE_ACCOUNT": "hsos-tasks-invoker@hsos-staging-example.iam.gserviceaccount.com",  # noqa: E501
    "HSOS_CLOUD_TASKS_LOCATION": "us-central1",
}


def env_file(name: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (DEPLOY / name).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, value = line.split(":", 1)
        out[key.strip()] = value.strip().strip("'\"")
    return out


@pytest.mark.parametrize("name", ["api.env.yaml", "worker.env.yaml"])
def test_staging_env_files_are_accepted(clean_env: pytest.MonkeyPatch, name: str) -> None:
    for key, value in {**env_file(name), **INJECTED}.items():
        clean_env.setenv(key, value)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.app_env is AppEnv.STAGING and settings.is_deployed
    assert settings.log_format == "json" and not settings.uses_emulators
    assert settings.reminder_provider is ReminderProvider.FAKE
    assert settings.reminder_test_recipients  # the guard is always on when deployed
    assert settings.sse_max_stream_seconds < 900  # Cloud Run API request timeout


def test_scheduler_jobs_target_existing_worker_routes() -> None:
    from app.workers.run_worker import router

    script = (DEPLOY / "provision.sh").read_text()
    routes = {r.path for r in router.routes}  # type: ignore[attr-defined]
    jobs = [line.split()[-1] for line in script.splitlines() if line.startswith("schedule hsos-")]
    assert jobs and set(jobs) <= routes
    assert set(routes) - set(jobs) == {"/internal/runs/execute", "/internal/consumers/process"}
    json.loads((DEPLOY.parent / "monitoring" / "alert-ops.json").read_text())
