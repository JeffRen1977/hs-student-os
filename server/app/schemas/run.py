from __future__ import annotations

from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from app.domain.types.run import TERMINAL_RUN_STATUSES, InputRequestKind, RunKind, RunStatus
from app.schemas.common import ApiModel, OpaqueId, RequestModel


class InputRequest(ApiModel):
    input_request_id: OpaqueId
    kind: InputRequestKind
    prompt: Annotated[str, StringConstraints(max_length=500)]


class RunResult(ApiModel):
    message_id: OpaqueId | None = None
    assessment_id: OpaqueId | None = None
    plan_id: OpaqueId | None = None


class RunError(ApiModel):
    """Safe, student-facing failure info. No stack traces or provider messages."""

    code: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")]
    retryable: bool


class Run(ApiModel):
    run_id: OpaqueId
    session_id: OpaqueId | None
    status: RunStatus
    kind: RunKind
    submission_id: OpaqueId | None = None
    message_id: OpaqueId | None = None
    attempt_count: int = Field(ge=0)
    input_request: InputRequest | None
    result: RunResult | None
    error: RunError | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.session_id is None and self.kind is not RunKind.PLANNING:
            raise ValueError("only PLANNING runs may have sessionId=null")
        if (self.status is RunStatus.WAITING_INPUT) != (self.input_request is not None):
            raise ValueError("inputRequest is present exactly when status is WAITING_INPUT")
        if self.result is not None and self.status is not RunStatus.SUCCEEDED:
            raise ValueError("result is only present on SUCCEEDED runs")
        if self.error is not None and self.status is not RunStatus.FAILED:
            raise ValueError("error is only present on FAILED runs")
        if self.kind is RunKind.ASSESS_SUBMISSION and self.submission_id is None:
            raise ValueError("ASSESS_SUBMISSION runs reference a submission")
        return self

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_RUN_STATUSES


class OcrConfirmation(RequestModel):
    confirmed_text: Annotated[str, StringConstraints(min_length=1, max_length=20_000)]


class RunInputRequest(RequestModel):
    """`POST /api/runs/{runId}/input`. Only the typed value the server asked for."""

    input_request_id: OpaqueId
    value: OcrConfirmation


class CommandAccepted(ApiModel):
    """202 body for commands that enqueue a Run."""

    run_id: OpaqueId
    status: RunStatus
