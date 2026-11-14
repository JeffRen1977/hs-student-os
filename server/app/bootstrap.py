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
from app.adapters.firestore.package_repository import (
    DocumentPackageUnitOfWork,
    FirestorePlatformDirectory,
)
from app.adapters.firestore.parent_repository import FirestoreParentDirectory
from app.adapters.firestore.unit_of_work import DocumentUnitOfWork
from app.adapters.llm.gateway import Gateway
from app.adapters.llm.provider import LlmProvider as LlmProviderAdapter
from app.adapters.llm.router import ModelRouter
from app.adapters.queue.local_queue import LocalQueue
from app.adapters.runtime import RandomIdFactory, SystemClock
from app.adapters.tools.math_verify import MathVerifyTool
from app.config import (
    AppEnv,
    ConfigError,
    LlmProvider,
    QueueProvider,
    ReminderProvider,
    Settings,
    StorageProvider,
)
from app.domain.admissions_runs import AdmissionsRunner
from app.domain.admissions_service import AdmissionsService
from app.domain.assessment_service import AssessmentService
from app.domain.budget import BudgetLedger, BudgetLimits
from app.domain.command_service import CommandService
from app.domain.course_service import CourseService
from app.domain.event_feed import EventFeedService
from app.domain.events import EventPublisher
from app.domain.local_time import parse_hhmm
from app.domain.mastery_service import MasteryService
from app.domain.ops_monitor import AlertThresholds, OpsMonitor
from app.domain.package_service import PackageService
from app.domain.parent_service import ParentService
from app.domain.planner_service import PlannerService
from app.domain.planning_schedule import PlanningSchedulePolicy
from app.domain.ports.catalog import CourseCatalog
from app.domain.ports.content import ModelTier, SubjectPackRegistry
from app.domain.ports.execution import JobQueue, RunExecutor
from app.domain.ports.identity import TokenVerifier
from app.domain.ports.metrics import Metrics
from app.domain.ports.notifications import ReminderSender
from app.domain.ports.packages import PlatformDirectory
from app.domain.ports.repositories import (
    IdentityDirectory,
    OperationsStore,
    ParentDirectory,
    UnitOfWork,
)
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.recovery import RecoveryService
from app.domain.reminder_service import ReminderPolicy, ReminderService
from app.domain.retention import EventRetention
from app.domain.run_execution import RunExecutionService
from app.domain.session_service import SessionService
from app.domain.skill_executor import SkillExecutor
from app.domain.task_service import TaskService
from app.domain.twin_service import TwinService
from app.registries.admissions_content import load_prompt_set
from app.registries.content import ContentRegistry, load_content
from app.registries.course_catalog import RegistryCourseCatalog
from app.registries.package_sync import PackageContentSync
from app.registries.package_validator import PlatformPackageValidator
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
from app.workers.scheduler.planning_scheduler import PlanningScheduler


@dataclass(slots=True, kw_only=True)
class Services:
    settings: Settings
    store: DocumentStore
    uow: UnitOfWork
    operations: OperationsStore
    identities: IdentityDirectory
    platform_members: PlatformDirectory
    parent_directory: ParentDirectory
    parents: ParentService
    admissions: AdmissionsService
    content: ContentRegistry
    content_sync: PackageContentSync
    packages: PackageService
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
    planning_scheduler: PlanningScheduler
    reminders: ReminderService
    metrics: Metrics
    ops_monitor: OpsMonitor
    event_retention: EventRetention
    consumers: ConsumerRunner
    deliveries: DeliveryRouter
    local_worker: LocalWorkerLoop | None


def seeded_memory_store() -> MemoryDocumentStore:
    from app.adapters.seed_documents import build_platform_documents, build_seed_documents
    from app.registries.fixtures import load_platform_fixture, load_seed_students

    now = datetime.now(UTC)
    return MemoryDocumentStore(
        {
            **build_seed_documents(load_seed_students(), now=now),
            **build_platform_documents(load_platform_fixture(), now=now),
        }
    )


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


def reminder_sender(settings: Settings) -> ReminderSender | None:
    """No real channel provider yet. Deployed environments (and local runs that list test
    recipients) only ever deliver to designated synthetic test students."""
    if settings.reminder_provider is ReminderProvider.DISABLED:
        return None
    from app.adapters.notifications.senders import FakeReminderSender, TestRecipientGuard

    sender: ReminderSender = FakeReminderSender()
    if settings.is_deployed or settings.reminder_test_recipients:
        sender = TestRecipientGuard(sender, settings.reminder_test_recipients)
    return sender


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


def _gateway(
    settings: Settings, provider: LlmProviderAdapter | None, ledger: BudgetLedger
) -> Gateway | None:
    """The budgeted model gateway, or None under `mock` (no model: never grading)."""
    if provider is None:
        if settings.llm_provider is LlmProvider.MOCK:
            return None
        provider = real_llm_provider(settings)
    return Gateway(
        provider,
        model_router(settings),
        ledger,
        max_attempts=settings.llm_max_attempts,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def _executor(
    gateway: Gateway | None, packs: SubjectPackRegistry, clock: Clock, ids: IdFactory
) -> RunExecutor:
    """`mock` → labeled synthetic replies, never assessments. A real provider (or an injected
    test provider) → the skill runtime behind the budgeted gateway."""
    if gateway is None:
        # Key-scored SAT items still run for real; everything needing a model is the
        # labeled synthetic fallback.
        return SkillExecutor(
            None, packs, ToolRegistry([MathVerifyTool()]), clock, ids,
            fallback=SyntheticExecutor(),
        )  # fmt: skip
    return SkillExecutor(gateway, packs, ToolRegistry([MathVerifyTool()]), clock, ids)


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
    reminder_sender_override: ReminderSender | None = None,
    metrics: Metrics | None = None,
) -> Services:
    """`consumers`: event consumers to run in addition to the platform's own. The platform
    registers the course-metrics consumer (Step 34.4) unless disabled; course follow-up
    rules arrive with Step 24.2. Tests pass their own."""
    store = store or _store(settings)
    if settings.course_metrics_enabled:
        from app.workers.consumers.course_metrics import CourseMetricsConsumer

        consumers = (*consumers, CourseMetricsConsumer())
    if metrics is None:
        from app.adapters.observability import LogMetrics

        metrics = LogMetrics()
    clock = clock or SystemClock()
    ids = ids or RandomIdFactory()
    # Bundled packs now; reviewed course packages are installed by `content_sync` from the
    # package store (at startup, after each activation/retirement, and when stale).
    content = load_content()
    catalog = catalog or RegistryCourseCatalog(content)
    packs = ContentSubjectPackRegistry(content, require_reviewed=settings.require_reviewed_content)
    uow = DocumentUnitOfWork(store)
    package_uow = DocumentPackageUnitOfWork(store)
    content_sync = PackageContentSync(
        content, package_uow, max_age_seconds=settings.package_refresh_seconds
    )
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
    assessments = AssessmentService(uow, packs, clock, ids, publisher, catalog=catalog)
    operations = FirestoreOperationsStore(store)
    schedule = PlanningSchedulePolicy(local_time=parse_hhmm(settings.planning_local_time))
    sender = reminder_sender_override or reminder_sender(settings)
    reminders = ReminderService(
        uow,
        operations,
        sender,
        clock,
        ReminderPolicy(
            enabled=sender is not None,
            local_time=parse_hhmm(settings.reminder_local_time),
            weekly_cap=settings.reminder_weekly_cap,
        ),
        metrics,
    )
    planner = PlannerService(uow, packs, clock, ids, reminders=reminders, catalog=catalog)
    planning_scheduler = PlanningScheduler(uow, operations, clock, ids, schedule)
    queue = queue or _queue(settings)
    dispatcher = OutboxDispatcher(uow, operations, queue, clock, metrics)
    gateway = _gateway(settings, llm_provider, ledger)
    prompt_set = load_prompt_set()
    run_execution = RunExecutionService(
        uow,
        catalog,
        executor or _executor(gateway, packs, clock, ids),
        clock,
        ids,
        worker_id=worker_id or f"worker-{socket.gethostname()}-{ids.new('w')}",
        lease_seconds=settings.run_lease_seconds,
        max_attempts=settings.run_max_attempts,
        packs=packs,
        assessments=assessments,
        planner=planner,
        metrics=metrics,
        admissions=AdmissionsRunner(gateway, prompt_set.by_id, ids),
        content=content_sync,
    )
    consumer_runner = ConsumerRunner(uow, consumers, clock)
    deliveries = DeliveryRouter(run_execution, consumer_runner, content_sync.ensure_fresh)
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
            scans=(planning_scheduler.run_due, reminders.deliver_due),
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
        platform_members=FirestorePlatformDirectory(store),
        parent_directory=FirestoreParentDirectory(store),
        parents=ParentService(uow, catalog, clock, ids),
        admissions=AdmissionsService(uow, prompt_set, clock, ids),
        content=content,
        content_sync=content_sync,
        packages=PackageService(
            package_uow,
            PlatformPackageValidator(),
            content_sync,
            clock,
            reserved_course_ids=content.bundled_course_ids,
        ),
        catalog=catalog,
        packs=packs,
        budget=ledger,
        clock=clock,
        ids=ids,
        token_verifier=token_verifier or FirebaseTokenVerifier(settings, clock),
        service_authenticator=_service_authenticator(settings),
        queue=queue,
        dispatcher=dispatcher,
        twin=TwinService(uow, catalog, clock, schedule),
        courses=CourseService(uow, catalog, clock, ids, schedule),
        tasks=TaskService(uow, catalog, clock),
        sessions=SessionService(uow, catalog, clock, ids, packs),
        commands=CommandService(uow, catalog, clock, ids, ledger),
        run_execution=run_execution,
        assessments=assessments,
        mastery=MasteryService(uow, catalog),
        events=EventFeedService(uow),
        recovery=recovery,
        planner=planner,
        planning_scheduler=planning_scheduler,
        reminders=reminders,
        metrics=metrics,
        ops_monitor=OpsMonitor(
            operations,
            clock,
            metrics,
            AlertThresholds(
                outbox_backlog=settings.alert_outbox_backlog,
                outbox_age_seconds=settings.alert_outbox_age_seconds,
                failed_runs_per_hour=settings.alert_failed_runs_per_hour,
                budget_overruns_per_hour=settings.alert_budget_overruns_per_hour,
            ),
        ),
        event_retention=EventRetention(
            uow, operations, clock, retention_days=settings.event_retention_days
        ),
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
