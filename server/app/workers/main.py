"""Worker service entry point: `uvicorn app.workers.main:app` (separate Cloud Run service)."""

from __future__ import annotations

from app.workers.run_worker import create_worker_app

app = create_worker_app()
