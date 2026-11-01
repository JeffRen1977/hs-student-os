from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from app.domain.types.session import CompletionBlocker, SessionStatus
from app.schemas.common import ApiModel, OpaqueId, RequestModel


class ContextVersion(ApiModel):
    pack: str
    workflow: str


class CompletionEligibility(ApiModel):
    eligible: bool
    reason: CompletionBlocker | None

    @model_validator(mode="after")
    def _reason_matches(self) -> Self:
        if self.eligible == (self.reason is not None):
            raise ValueError("eligible sessions have no reason; ineligible ones need one")
        return self


class SessionActivity(ApiModel):
    """The question this session works on, at the version pinned when it opened."""

    question_id: OpaqueId
    question_version: str
    topic: str
    prompt: str


class Session(ApiModel):
    session_id: OpaqueId
    task_id: OpaqueId
    status: SessionStatus
    active_run_id: OpaqueId | None
    context_version: ContextVersion
    completion: CompletionEligibility
    activity: SessionActivity | None = None
    hint_count: int = Field(default=0, ge=0)  # server-issued hints so far

    @model_validator(mode="after")
    def _closed_sessions_have_no_active_run(self) -> Self:
        if self.status is not SessionStatus.OPEN and self.active_run_id is not None:
            raise ValueError("only OPEN sessions can have an active run")
        return self


class SessionList(ApiModel):
    sessions: list[Session]
    next_cursor: str | None


class CreateSessionRequest(RequestModel):
    """`POST /api/sessions`. Course, agent, mode and skills are derived from the Task."""

    task_id: OpaqueId
