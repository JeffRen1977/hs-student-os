"""Cloud Tasks queue adapter (Step 15.2). Wired and unit-tested; verified in staging (Step 30).

Each delivery becomes an HTTP task to the worker service with an OIDC token for the
configured service account. The task name is the deterministic delivery id, so Cloud Tasks
de-duplicates re-enqueues inside its dedup window; outside it, the worker's lease and
fencing checks make duplicates harmless.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.domain.types.outbox import Delivery, OutboxKind

_TASK_NAME_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def task_name_for(delivery_id: str) -> str:
    return _TASK_NAME_SAFE.sub("-", delivery_id)[:500]


class CloudTasksQueue:
    def __init__(
        self,
        client: Any,
        *,
        project: str,
        location: str,
        queue: str,
        worker_url: str,
        service_account_email: str,
        audience: str,
    ) -> None:
        self._client = client
        self._parent = client.queue_path(project, location, queue)
        base = worker_url.rstrip("/")
        self._urls = {
            OutboxKind.RUN: base + "/internal/runs/execute",
            OutboxKind.CONSUMERS: base + "/internal/consumers/process",
        }
        self._service_account = service_account_email
        self._audience = audience

    def build_task(self, delivery: Delivery) -> dict[str, Any]:
        body: dict[str, str] = {
            "deliveryId": delivery.delivery_id,
            "studentId": delivery.student_id,
        }
        if delivery.run_id is not None:
            body["runId"] = delivery.run_id
        return {
            "name": f"{self._parent}/tasks/{task_name_for(delivery.delivery_id)}",
            "http_request": {
                "http_method": "POST",
                "url": self._urls[delivery.kind],
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(body).encode(),
                "oidc_token": {
                    "service_account_email": self._service_account,
                    "audience": self._audience,
                },
            },
        }

    async def enqueue(self, delivery: Delivery) -> None:
        from google.api_core.exceptions import AlreadyExists

        try:
            await self._client.create_task(parent=self._parent, task=self.build_task(delivery))
        except AlreadyExists:
            return  # same delivery id already enqueued: nothing to do
