from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.domain.types.assessment_draft import AssessmentDraft
from app.domain.types.course import CourseDefinition
from app.domain.types.message import Message
from app.domain.types.outbox import Delivery
from app.domain.types.run import Run
from app.domain.types.session import Session
from app.domain.types.submission import Submission
from app.domain.types.tool import ToolResult


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionRequest:
    run: Run
    session: Session
    course: CourseDefinition
    student_text: str
    history: Sequence[Message] = ()
    submission: Submission | None = None
    student_name: str = ""
    mastery_context: str = ""
    mode: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionOutput:
    agent_text: str
    model_version: str
    synthetic: bool
    # Set when the agent reply was a server-issued hint (counted for hint dependency).
    issued_hint: bool = False
    # Set by assessment runs; committed atomically with the Run's terminal state.
    assessment: AssessmentDraft | None = None
    tool_results: Sequence[ToolResult] = ()
    usage_tokens: int = 0


class RetryableExecutionError(Exception):
    """Transient failure (provider timeout, rate limit); the run may be retried."""


class ExecutionFailure(Exception):
    """Permanent failure with a safe, student-facing error code (e.g. BUDGET_EXCEEDED)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RunExecutor(Protocol):
    async def execute(self, request: ExecutionRequest) -> ExecutionOutput: ...


class JobQueue(Protocol):
    async def enqueue(self, delivery: Delivery) -> None:
        """Deliver at least once. Re-enqueueing the same delivery_id must be harmless."""
        ...
