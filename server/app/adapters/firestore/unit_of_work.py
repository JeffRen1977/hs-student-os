from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.adapters.firestore.assessment_repository import (
    FirestoreAssessmentStore,
    FirestoreMasteryStore,
)
from app.adapters.firestore.course_repository import FirestoreEnrollmentStore
from app.adapters.firestore.documents import DocTxn, DocumentStore
from app.adapters.firestore.event_repository import FirestoreEventStore
from app.adapters.firestore.idempotency_repository import FirestoreIdempotencyStore
from app.adapters.firestore.message_repository import FirestoreMessageStore
from app.adapters.firestore.outbox_repository import FirestoreFileStore, FirestoreOutboxStore
from app.adapters.firestore.run_repository import FirestoreRunInputStore, FirestoreRunStore
from app.adapters.firestore.session_repository import FirestoreSessionStore
from app.adapters.firestore.student_repository import FirestoreStudentStore
from app.adapters.firestore.submission_repository import FirestoreSubmissionStore
from app.adapters.firestore.task_repository import FirestoreTaskStore
from app.adapters.firestore.usage_repository import FirestoreToolResultStore, FirestoreUsageStore
from app.domain.ports.repositories import Tx


class FirestoreTx:
    """All stores bound to one transaction."""

    def __init__(self, txn: DocTxn) -> None:
        self.students = FirestoreStudentStore(txn)
        self.enrollments = FirestoreEnrollmentStore(txn)
        self.tasks = FirestoreTaskStore(txn)
        self.sessions = FirestoreSessionStore(txn)
        self.messages = FirestoreMessageStore(txn)
        self.submissions = FirestoreSubmissionStore(txn)
        self.runs = FirestoreRunStore(txn)
        self.run_inputs = FirestoreRunInputStore(txn)
        self.files = FirestoreFileStore(txn)
        self.idempotency = FirestoreIdempotencyStore(txn)
        self.events = FirestoreEventStore(txn)
        self.outbox = FirestoreOutboxStore(txn)
        self.assessments = FirestoreAssessmentStore(txn)
        self.mastery = FirestoreMasteryStore(txn)
        self.usage = FirestoreUsageStore(txn)
        self.tool_results = FirestoreToolResultStore(txn)


class DocumentUnitOfWork:
    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    async def transaction[T](self, fn: Callable[[Tx], Awaitable[T]]) -> T:
        async def body(txn: DocTxn) -> T:
            return await fn(FirestoreTx(txn))

        return await self._store.run_transaction(body)
