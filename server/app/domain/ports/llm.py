"""The controlled interface every model call goes through (Step 16, BACKEND.md §7).

Domain skills build an `LlmRequest`; the gateway adapter routes it to a model by tier,
enforces budgets, retries finitely, validates the output with the caller's `parse`, and
reports usage with the model and workflow versions.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from app.domain.ports.content import ModelTier
from app.domain.ports.execution import ExecutionFailure, RetryableExecutionError
from app.domain.types.usage import BudgetScope


class LlmRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class Effort(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True, kw_only=True)
class LlmMessage:
    role: LlmRole
    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class BudgetContext:
    student_id: str
    session_id: str | None
    run_id: str


@dataclass(frozen=True, slots=True, kw_only=True)
class LlmRequest:
    purpose: str  # skill name, e.g. "rubric-assessment"; drives routing and logs
    pack_tier: ModelTier
    workflow_version: str
    system: str
    messages: Sequence[LlmMessage]
    output_schema: Mapping[str, Any]  # JSON schema for structured output
    max_output_tokens: int
    effort: Effort
    budget: BudgetContext


@dataclass(frozen=True, slots=True, kw_only=True)
class LlmUsage:
    input_tokens: int
    output_tokens: int

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True, kw_only=True)
class LlmResult[T]:
    value: T
    model_version: str
    workflow_version: str
    tier: ModelTier
    usage: LlmUsage  # summed over every attempt, failed ones included
    attempts: int


class LlmUnavailableError(RetryableExecutionError):
    """Provider timeouts/outages after the gateway's own finite retries."""


class LlmOutputInvalidError(ExecutionFailure):
    def __init__(self) -> None:
        super().__init__("MODEL_OUTPUT_INVALID")


class LlmRefusedError(ExecutionFailure):
    def __init__(self) -> None:
        super().__init__("MODEL_REFUSED")


class LlmConfigurationError(ExecutionFailure):
    def __init__(self) -> None:
        super().__init__("MODEL_UNAVAILABLE")


class BudgetExceededError(ExecutionFailure):
    def __init__(self, scope: BudgetScope) -> None:
        super().__init__("BUDGET_EXCEEDED")
        self.scope = scope


class LlmGateway(Protocol):
    async def generate[T](self, request: LlmRequest, parse: Callable[[Any], T]) -> LlmResult[T]:
        """`parse` receives the decoded JSON and raises ValueError if it is unusable."""
        ...
