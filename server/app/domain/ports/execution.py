from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.domain.types.course import CourseDefinition
from app.domain.types.message import Message
from app.domain.types.outbox import Delivery
from app.domain.types.run import Run
from app.domain.types.session import Session


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionRequest:
    run: Run
    session: Session
    course: CourseDefinition
    student_text: str
    history: Sequence[Message] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionOutput:
    agent_text: str
    model_version: str
    synthetic: bool


class RetryableExecutionError(Exception):
    """Transient failure (provider timeout, rate limit); the run may be retried."""


class RunExecutor(Protocol):
    async def execute(self, request: ExecutionRequest) -> ExecutionOutput: ...


class JobQueue(Protocol):
    async def enqueue(self, delivery: Delivery) -> None:
        """Deliver at least once. Re-enqueueing the same delivery_id must be harmless."""
        ...
