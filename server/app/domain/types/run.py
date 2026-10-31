from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    WAITING_INPUT = "WAITING_INPUT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_RUN_STATUSES = frozenset({RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED})

RUN_TRANSITIONS: Mapping[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset(
        {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.WAITING_INPUT}
    ),
    RunStatus.WAITING_INPUT: frozenset({RunStatus.QUEUED, RunStatus.CANCELLED}),
    RunStatus.SUCCEEDED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


class RunKind(StrEnum):
    ASSESS_SUBMISSION = "ASSESS_SUBMISSION"
    HINT = "HINT"  # reply to a student message; never independent evidence
    PLANNING = "PLANNING"  # student-scoped, may have no session


class InputRequestKind(StrEnum):
    OCR_CONFIRMATION = "OCR_CONFIRMATION"


@dataclass(frozen=True, slots=True, kw_only=True)
class InputRequest:
    input_request_id: str
    kind: InputRequestKind
    prompt: str


@dataclass(frozen=True, slots=True, kw_only=True)
class RunResult:
    message_id: str | None = None
    assessment_id: str | None = None
    plan_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class RunError:
    code: str
    retryable: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class Run:
    run_id: str
    student_id: str
    session_id: str | None
    status: RunStatus
    kind: RunKind
    submission_id: str | None = None
    message_id: str | None = None
    attempt_count: int = 0
    input_request: InputRequest | None = None
    result: RunResult | None = None
    error: RunError | None = None
    cancel_requested: bool = False
    lease_fencing_token: int = 0
    # Internal execution bookkeeping (never exposed to clients).
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    dispatch_generation: int = 1  # bumped whenever the run is re-queued for delivery
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.session_id is None and self.kind is not RunKind.PLANNING:
            raise ValueError("only PLANNING runs may omit session_id")

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_RUN_STATUSES

    def lease_active(self, now: datetime) -> bool:
        return (
            self.status is RunStatus.RUNNING
            and self.lease_expires_at is not None
            and self.lease_expires_at > now
        )

    @property
    def delivery_id(self) -> str:
        """Deterministic delivery id: one per (run, dispatch generation)."""
        return f"{self.run_id}.g{self.dispatch_generation}"
