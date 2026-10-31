"""Shared harness for M1 tests: real token verification (emulator mode, no network),
the in-memory document store seeded with the synthetic fixtures, a controllable clock,
and deterministic ids.

The in-memory store gives all-or-nothing transactions but is not proof that Firestore
behaves the same; `tests/emulator/` re-runs the critical flows against the emulator.
"""

from __future__ import annotations

import base64
import itertools
import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.adapters.firestore.memory_store import MemoryDocumentStore
from app.adapters.firestore.task_repository import task_to_doc
from app.adapters.queue.local_queue import LocalQueue
from app.adapters.seed_documents import build_seed_documents
from app.bootstrap import Services, build_services
from app.config import Settings, StorageProvider
from app.domain.ports.execution import RunExecutor
from app.domain.types.common import AgentType, StudyMode, TaskType
from app.domain.types.task import Task, TaskReason, TaskReasonCode, TaskStatus
from app.main import create_app
from app.registries.fixtures import load_seed_students

PROJECT = "demo-hs-student-os"
START = datetime(2026, 11, 2, 18, 0, tzinfo=UTC)  # 10:00 in Los Angeles, 13:00 in New York


class FakeClock:
    def __init__(self, now: datetime = START) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now

    def advance(self, **delta: float) -> None:
        self._now += timedelta(**delta)


class SequentialIds:
    def __init__(self) -> None:
        self._n = itertools.count(1)

    def new(self, prefix: str) -> str:
        return f"{prefix}_{next(self._n):05d}"


def _b64(data: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def emulator_token(uid: str, *, now: datetime = START, **overrides: Any) -> str:
    """An unsigned Auth-emulator-style ID token (accepted only in emulator mode)."""
    ts = int(now.timestamp())
    claims: dict[str, Any] = {
        "iss": f"https://securetoken.google.com/{PROJECT}",
        "aud": PROJECT,
        "auth_time": ts,
        "user_id": uid,
        "sub": uid,
        "iat": ts,
        "exp": ts + 3600,
        "firebase": {"identities": {}, "sign_in_provider": "password"},
    }
    claims.update(overrides)
    return f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(claims)}."


def idem() -> str:
    return "idk_" + secrets.token_hex(12)


def make_task(
    student_id: str,
    task_id: str,
    *,
    course_id: str = "calc_bc",
    scheduled: date = date(2026, 11, 2),
    status: TaskStatus = TaskStatus.PLANNED,
    agent: AgentType = AgentType.AP_BASE,
) -> Task:
    return Task(
        task_id=task_id,
        student_id=student_id,
        agent=agent,
        course_id=course_id,
        task_type=TaskType.FRQ_PRACTICE,
        mode=StudyMode.GPA_SYNC,
        title=f"Practice {task_id}",
        duration_min=20,
        scheduled_date=scheduled,
        status=status,
        version=1,
        reason=TaskReason(code=TaskReasonCode.INITIAL_PRACTICE),
    )


@dataclass
class Harness:
    store: MemoryDocumentStore
    clock: FakeClock
    services: Services
    queue: LocalQueue
    client: AsyncClient
    tokens: dict[str, str] = field(default_factory=dict)

    def auth(self, student_id: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {emulator_token(student_id, now=self.clock.now())}"}

    def cmd(self, student_id: str, key: str | None = None) -> dict[str, str]:
        return {**self.auth(student_id), "Idempotency-Key": key or idem()}

    def put_task(self, task: Task) -> None:
        self.store.put(
            f"students/{task.student_id}/tasks/{task.task_id}",
            {**task_to_doc(task), "updatedAt": self.clock.now()},
        )

    def put_doc(self, path: str, data: dict[str, Any]) -> None:
        self.store.put(path, data)

    async def drain(self) -> int:
        """Run one local worker cycle: dispatch the outbox, then execute deliveries."""
        await self.services.dispatcher.dispatch_pending()
        return await self.queue.drain(self.services.run_execution.process)


def harness_settings(monkeypatch: pytest.MonkeyPatch, **overrides: Any) -> Settings:
    # Emulator mode makes the Firebase Admin SDK accept unsigned emulator tokens. Nothing
    # listens on these hosts: storage is in-memory and verification is offline.
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:9")
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        gcp_project_id=PROJECT,
        storage_provider=StorageProvider.MEMORY,
        local_worker_enabled=False,
        **overrides,
    )


def build_harness(
    monkeypatch: pytest.MonkeyPatch,
    *,
    executor: RunExecutor | None = None,
    **settings_overrides: Any,
) -> Harness:
    settings = harness_settings(monkeypatch, **settings_overrides)
    clock = FakeClock()
    store = MemoryDocumentStore(build_seed_documents(load_seed_students(), now=clock.now()))
    queue = LocalQueue()
    services = build_services(
        settings,
        store=store,
        clock=clock,
        ids=SequentialIds(),
        queue=queue,
        executor=executor,
        worker_id="worker-test",
    )
    app = create_app(settings, services)
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    client = AsyncClient(transport=transport, base_url="http://test")
    return Harness(store=store, clock=clock, services=services, queue=queue, client=client)
