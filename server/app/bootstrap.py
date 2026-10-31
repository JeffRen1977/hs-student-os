"""Composition root: build adapters and domain services from Settings.

Only this module (and tests) choose concrete adapters. Everything else depends on ports.
Construction is lazy so that importing `app.main` never touches cloud credentials.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import Request

from app.adapters.auth import FirebaseTokenVerifier
from app.adapters.execution.synthetic import SyntheticExecutor
from app.adapters.firestore.documents import DocumentStore
from app.adapters.firestore.identity_repository import FirestoreIdentityDirectory
from app.adapters.firestore.memory_store import MemoryDocumentStore
from app.adapters.firestore.outbox_repository import FirestoreOperationsStore
from app.adapters.firestore.unit_of_work import DocumentUnitOfWork
from app.adapters.queue.local_queue import LocalQueue
from app.adapters.runtime import RandomIdFactory, SystemClock
from app.config import AppEnv, ConfigError, LlmProvider, QueueProvider, Settings, StorageProvider
from app.domain.command_service import CommandService
from app.domain.course_service import CourseService
from app.domain.ports.catalog import CourseCatalog
from app.domain.ports.execution import JobQueue, RunExecutor
from app.domain.ports.identity import TokenVerifier
from app.domain.ports.repositories import IdentityDirectory, OperationsStore, UnitOfWork
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.recovery import RecoveryService
from app.domain.run_execution import RunExecutionService
from app.domain.session_service import SessionService
from app.domain.task_service import TaskService
from app.domain.twin_service import TwinService
from app.registries.content import load_content
from app.registries.course_catalog import RegistryCourseCatalog
from app.workers.auth import (
    DenyAllAuthenticator,
    GoogleOidcAuthenticator,
    LocalServiceTokenAuthenticator,
    ServiceAuthenticator,
)
from app.workers.local_runner import LocalWorkerLoop
from app.workers.outbox_dispatcher import OutboxDispatcher


@dataclass(slots=True, kw_only=True)
class Services:
    settings: Settings
    store: DocumentStore
    uow: UnitOfWork
    operations: OperationsStore
    identities: IdentityDirectory
    catalog: CourseCatalog
    clock: Clock
    ids: IdFactory
    token_verifier: TokenVerifier
    service_authenticator: ServiceAuthenticator
    queue: JobQueue
    dispatcher: OutboxDispatcher
    twin: TwinService
    courses: CourseService
    tasks: TaskService
    sessions: SessionService
    commands: CommandService
    run_execution: RunExecutionService
    recovery: RecoveryService
    local_worker: LocalWorkerLoop | None


def seeded_memory_store() -> MemoryDocumentStore:
    from app.adapters.seed_documents import build_seed_documents
    from app.registries.fixtures import load_seed_students

    return MemoryDocumentStore(build_seed_documents(load_seed_students(), now=datetime.now(UTC)))


def _store(settings: Settings) -> DocumentStore:
    if settings.storage_provider is StorageProvider.MEMORY:
        if settings.is_deployed:  # Settings already rejects this; defense in depth.
            raise ConfigError("memory storage is not allowed in deployed environments")
        return seeded_memory_store()
    from app.adapters.firebase import create_async_firestore_client
    from app.adapters.firestore.client_store import FirestoreDocumentStore

    if settings.app_env in (AppEnv.LOCAL, AppEnv.TEST) and not settings.uses_emulators:
        raise ConfigError(
            "local Firestore needs the emulators (make emulators) or HSOS_STORAGE_PROVIDER=memory"
        )
    return FirestoreDocumentStore(create_async_firestore_client(settings))


def _service_authenticator(settings: Settings) -> ServiceAuthenticator:
    if settings.worker_service_token is not None and not settings.is_deployed:
        return LocalServiceTokenAuthenticator(settings.worker_service_token)
    if settings.worker_oidc_audience and settings.worker_service_account:
        return GoogleOidcAuthenticator(
            audience=settings.worker_oidc_audience,
            service_account=settings.worker_service_account,
        )
    return DenyAllAuthenticator()


def _queue(settings: Settings) -> JobQueue:
    if settings.queue_provider is QueueProvider.LOCAL:
        return LocalQueue()
    from google.cloud import tasks_v2

    from app.adapters.queue.cloud_tasks_adapter import CloudTasksQueue

    missing = [
        name
        for name, value in (
            ("HSOS_CLOUD_TASKS_LOCATION", settings.cloud_tasks_location),
            ("HSOS_CLOUD_TASKS_QUEUE", settings.cloud_tasks_queue),
            ("HSOS_WORKER_URL", settings.worker_url),
            ("HSOS_WORKER_SERVICE_ACCOUNT", settings.worker_service_account),
            ("HSOS_WORKER_OIDC_AUDIENCE", settings.worker_oidc_audience),
        )
        if not value
    ]
    if missing:
        raise ConfigError("cloud_tasks queue needs: " + ", ".join(missing))
    assert settings.cloud_tasks_location and settings.cloud_tasks_queue and settings.worker_url
    assert settings.worker_service_account and settings.worker_oidc_audience
    return CloudTasksQueue(
        tasks_v2.CloudTasksAsyncClient(),
        project=settings.gcp_project_id,
        location=settings.cloud_tasks_location,
        queue=settings.cloud_tasks_queue,
        worker_url=settings.worker_url,
        service_account_email=settings.worker_service_account,
        audience=settings.worker_oidc_audience,
    )


def _executor(settings: Settings) -> RunExecutor:
    if settings.llm_provider is LlmProvider.MOCK:
        return SyntheticExecutor()
    # The Anthropic-backed LLMGateway lands in Step 16. Until then a non-mock provider
    # has no executor, and that must fail loudly rather than fall back to synthetic output.
    raise ConfigError("HSOS_LLM_PROVIDER=anthropic has no executor until Step 16 (LLMGateway)")


def build_services(
    settings: Settings,
    *,
    store: DocumentStore | None = None,
    clock: Clock | None = None,
    ids: IdFactory | None = None,
    token_verifier: TokenVerifier | None = None,
    executor: RunExecutor | None = None,
    queue: JobQueue | None = None,
    catalog: CourseCatalog | None = None,
    worker_id: str | None = None,
) -> Services:
    store = store or _store(settings)
    clock = clock or SystemClock()
    ids = ids or RandomIdFactory()
    catalog = catalog or RegistryCourseCatalog(load_content())
    uow = DocumentUnitOfWork(store)
    operations = FirestoreOperationsStore(store)
    queue = queue or _queue(settings)
    dispatcher = OutboxDispatcher(uow, operations, queue, clock)
    run_execution = RunExecutionService(
        uow,
        catalog,
        executor or _executor(settings),
        clock,
        ids,
        worker_id=worker_id or f"worker-{socket.gethostname()}-{ids.new('w')}",
        lease_seconds=settings.run_lease_seconds,
        max_attempts=settings.run_max_attempts,
    )
    recovery = RecoveryService(
        uow, operations, clock, requeue_after_seconds=settings.run_requeue_after_seconds
    )
    local_worker = (
        LocalWorkerLoop(
            queue=queue,
            dispatcher=dispatcher,
            recovery=recovery,
            execution=run_execution,
            poll_seconds=settings.local_worker_poll_seconds,
        )
        if isinstance(queue, LocalQueue)
        else None
    )
    return Services(
        settings=settings,
        store=store,
        uow=uow,
        operations=operations,
        identities=FirestoreIdentityDirectory(store),
        catalog=catalog,
        clock=clock,
        ids=ids,
        token_verifier=token_verifier or FirebaseTokenVerifier(settings, clock),
        service_authenticator=_service_authenticator(settings),
        queue=queue,
        dispatcher=dispatcher,
        twin=TwinService(uow, catalog, clock),
        courses=CourseService(uow, catalog, clock, ids),
        tasks=TaskService(uow, catalog, clock),
        sessions=SessionService(uow, catalog, clock, ids),
        commands=CommandService(uow, catalog, clock, ids),
        run_execution=run_execution,
        recovery=recovery,
        local_worker=local_worker,
    )


def get_services(request: Request) -> Services:
    """FastAPI dependency. Builds services on first use if startup did not."""
    state: Any = request.app.state
    services: Services | None = getattr(state, "services", None)
    if services is None:
        services = build_services(state.settings)
        state.services = services
    return services
