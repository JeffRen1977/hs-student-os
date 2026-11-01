"""Composition root: build adapters and domain services from Settings.

Only this module (and tests) choose concrete adapters. Everything else depends on ports.
Construction is lazy so that importing `app.main` never touches cloud credentials.
"""

from __future__ import annotations

import socket
from collections.abc import Sequence
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
from app.adapters.llm.gateway import Gateway
from app.adapters.llm.provider import LlmProvider as LlmProviderAdapter
from app.adapters.llm.router import ModelRouter
from app.adapters.queue.local_queue import LocalQueue
from app.adapters.runtime import RandomIdFactory, SystemClock
from app.adapters.tools.math_verify import MathVerifyTool
from app.config import AppEnv, ConfigError, LlmProvider, QueueProvider, Settings, StorageProvider
from app.domain.assessment_service import AssessmentService
from app.domain.budget import BudgetLedger, BudgetLimits
from app.domain.command_service import CommandService
from app.domain.course_service import CourseService
from app.domain.event_feed import EventFeedService
from app.domain.events import EventPublisher
from app.domain.mastery_service import MasteryService
from app.domain.planner_service import PlannerService
from app.domain.ports.catalog import CourseCatalog
from app.domain.ports.content import ModelTier, SubjectPackRegistry
from app.domain.ports.execution import JobQueue, RunExecutor
from app.domain.ports.identity import TokenVerifier
from app.domain.ports.repositories import IdentityDirectory, OperationsStore, UnitOfWork
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.recovery import RecoveryService
from app.domain.run_execution import RunExecutionService
from app.domain.session_service import SessionService
from app.domain.skill_executor import SkillExecutor
from app.domain.task_service import TaskService
from app.domain.twin_service import TwinService
from app.registries.content import ContentRegistry, load_content
from app.registries.course_catalog import RegistryCourseCatalog
from app.registries.subject_pack_registry import ContentSubjectPackRegistry
from app.registries.tool_registry import ToolRegistry
from app.workers.auth import (
    DenyAllAuthenticator,
    GoogleOidcAuthenticator,
    LocalServiceTokenAuthenticator,
    ServiceAuthenticator,
)
from app.workers.consumers.base import Consumer
from app.workers.consumers.runner import ConsumerRunner
from app.workers.delivery_router import DeliveryRouter
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
    packs: SubjectPackRegistry
    budget: BudgetLedger
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
    assessments: AssessmentService
    mastery: MasteryService
    events: EventFeedService
    recovery: RecoveryService
    planner: PlannerService
    consumers: ConsumerRunner
    deliveries: DeliveryRouter
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


def model_router(settings: Settings) -> ModelRouter:
    fast, balanced, strong = settings.llm_models()
    return ModelRouter(
        {ModelTier.FAST: fast, ModelTier.BALANCED: balanced, ModelTier.STRONG: strong}
    )


def real_llm_provider(settings: Settings) -> LlmProviderAdapter:
    """The configured real provider. Refuses `mock`: synthetic output is never grading."""
    if settings.llm_provider is LlmProvider.ANTHROPIC:
        from app.adapters.llm.anthropic_provider import AnthropicProvider

        key = settings.anthropic_api_key
        return AnthropicProvider.from_api_key(key.get_secret_value() if key else None)
    if settings.llm_provider is LlmProvider.OPENAI:
        from app.adapters.llm.openai_provider import OpenAIProvider

        key = settings.openai_api_key
        return OpenAIProvider.from_api_key(key.get_secret_value() if key else None)
    raise ConfigError(f"HSOS_LLM_PROVIDER={settings.llm_provider.value} is not a real provider")


def _executor(
    settings: Settings,
    provider: LlmProviderAdapter | None,
    packs: SubjectPackRegistry,
    ledger: BudgetLedger,
    clock: Clock,
    ids: IdFactory,
) -> RunExecutor:
    """`mock` → labeled synthetic replies, never assessments. A real provider (or an injected
    test provider) → the skill runtime behind the budgeted gateway."""
    if provider is None:
        if settings.llm_provider is LlmProvider.MOCK:
            # Key-scored SAT items still run for real; everything needing a model is the
            # labeled synthetic fallback.
            return SkillExecutor(
                None, packs, ToolRegistry([MathVerifyTool()]), clock, ids,
                fallback=SyntheticExecutor(),
            )  # fmt: skip
        provider = real_llm_provider(settings)
    gateway = Gateway(
        provider,
        model_router(settings),
        ledger,
        max_attempts=settings.llm_max_attempts,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    return SkillExecutor(gateway, packs, ToolRegistry([MathVerifyTool()]), clock, ids)


def _course_skills(content: ContentRegistry) -> dict[str, list[str]]:
    return {cid: sorted(pack.skill_ids) for cid, pack in content.packs.items()}


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
    llm_provider: LlmProviderAdapter | None = None,
    consumers: Sequence[Consumer] = (),
) -> Services:
    """`consumers`: the course-internal event consumers to run. None is registered in
    production yet (course follow-up rules arrive with Step 24.2); tests pass their own."""
    store = store or _store(settings)
    clock = clock or SystemClock()
    ids = ids or RandomIdFactory()
    content = load_content()
    catalog = catalog or RegistryCourseCatalog(content)
    packs = ContentSubjectPackRegistry(content, require_reviewed=settings.require_reviewed_content)
    uow = DocumentUnitOfWork(store)
    ledger = BudgetLedger(
        uow,
        clock,
        ids,
        BudgetLimits(
            run_tokens=settings.llm_run_token_budget,
            session_tokens=settings.llm_session_token_budget,
            daily_tokens=settings.llm_daily_token_budget,
        ),
    )
    publisher = EventPublisher(frozenset().union(*(c.subscribes for c in consumers)))
    assessments = AssessmentService(uow, packs, clock, ids, publisher)
    planner = PlannerService(uow, packs, clock, ids)
    operations = FirestoreOperationsStore(store)
    queue = queue or _queue(settings)
    dispatcher = OutboxDispatcher(uow, operations, queue, clock)
    run_execution = RunExecutionService(
        uow,
        catalog,
        executor or _executor(settings, llm_provider, packs, ledger, clock, ids),
        clock,
        ids,
        worker_id=worker_id or f"worker-{socket.gethostname()}-{ids.new('w')}",
        lease_seconds=settings.run_lease_seconds,
        max_attempts=settings.run_max_attempts,
        assessments=assessments,
        planner=planner,
    )
    consumer_runner = ConsumerRunner(uow, consumers, clock)
    deliveries = DeliveryRouter(run_execution, consumer_runner)
    recovery = RecoveryService(
        uow, operations, clock, requeue_after_seconds=settings.run_requeue_after_seconds
    )
    local_worker = (
        LocalWorkerLoop(
            queue=queue,
            dispatcher=dispatcher,
            recovery=recovery,
            execution=deliveries,
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
        packs=packs,
        budget=ledger,
        clock=clock,
        ids=ids,
        token_verifier=token_verifier or FirebaseTokenVerifier(settings, clock),
        service_authenticator=_service_authenticator(settings),
        queue=queue,
        dispatcher=dispatcher,
        twin=TwinService(uow, catalog, clock),
        courses=CourseService(uow, catalog, clock, ids),
        tasks=TaskService(uow, catalog, clock),
        sessions=SessionService(uow, catalog, clock, ids, packs),
        commands=CommandService(uow, catalog, clock, ids, ledger),
        run_execution=run_execution,
        assessments=assessments,
        mastery=MasteryService(uow, catalog, _course_skills(content)),
        events=EventFeedService(uow),
        recovery=recovery,
        planner=planner,
        consumers=consumer_runner,
        deliveries=deliveries,
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
