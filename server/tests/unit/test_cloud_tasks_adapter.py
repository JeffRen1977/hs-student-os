"""Step 15.2: Cloud Tasks adapter shape (verified against real Cloud Tasks in Step 30)."""

from __future__ import annotations

import json
from typing import Any

from google.api_core.exceptions import AlreadyExists

from app.adapters.queue.cloud_tasks_adapter import CloudTasksQueue, task_name_for
from app.domain.types.outbox import Delivery, OutboxKind


class FakeTasksClient:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    def queue_path(self, project: str, location: str, queue: str) -> str:
        return f"projects/{project}/locations/{location}/queues/{queue}"

    async def create_task(self, *, parent: str, task: dict[str, Any]) -> None:
        if any(t["name"] == task["name"] for t in self.created):
            raise AlreadyExists("duplicate")
        self.created.append(task)


def _queue(client: FakeTasksClient) -> CloudTasksQueue:
    return CloudTasksQueue(
        client,
        project="p",
        location="us-central1",
        queue="runs",
        worker_url="https://worker.example.test/",
        service_account_email="invoker@p.iam.gserviceaccount.com",
        audience="https://worker.example.test",
    )


async def test_task_is_named_by_delivery_and_carries_ids_only() -> None:
    client = FakeTasksClient()
    delivery = Delivery(delivery_id="run_1.g2", student_id="stu_alex", run_id="run_1")
    await _queue(client).enqueue(delivery)
    await _queue(client).enqueue(delivery)  # duplicate enqueue is swallowed
    [task] = client.created
    assert task["name"].endswith("/tasks/run_1-g2")
    request = task["http_request"]
    assert request["url"] == "https://worker.example.test/internal/runs/execute"
    assert request["oidc_token"]["service_account_email"] == "invoker@p.iam.gserviceaccount.com"
    assert json.loads(request["body"]) == {
        "deliveryId": "run_1.g2",
        "studentId": "stu_alex",
        "runId": "run_1",
    }


def test_task_names_are_sanitized() -> None:
    assert task_name_for("run_1.g1:x") == "run_1-g1-x"


async def test_consumer_wakes_go_to_the_consumer_endpoint_without_a_run_id() -> None:
    client = FakeTasksClient()
    wake = Delivery(
        delivery_id="wake.evt_1", student_id="stu_alex", run_id=None, kind=OutboxKind.CONSUMERS
    )
    await _queue(client).enqueue(wake)
    [task] = client.created
    assert task["http_request"]["url"] == "https://worker.example.test/internal/consumers/process"
    assert json.loads(task["http_request"]["body"]) == {
        "deliveryId": "wake.evt_1",
        "studentId": "stu_alex",
    }
