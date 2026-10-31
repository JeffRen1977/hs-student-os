from __future__ import annotations

from typing import Annotated

from pydantic import ConfigDict, Field, StringConstraints

from app.domain.types.run import RunStatus
from app.schemas.common import ApiModel, OpaqueId, RequestModel, UtcDatetime

AnswerText = Annotated[str, StringConstraints(min_length=1, max_length=20_000)]


class Answer(RequestModel):
    text: AnswerText
    file_ids: list[OpaqueId] = Field(default_factory=list, max_length=5)


class CreateSubmissionRequest(RequestModel):
    """`POST /api/sessions/{id}/submissions`. Content only — never scores or statuses.

    `extra="forbid"` rejects scoreDelta, outcome, score, assessmentStatus, mastery, etc.
    """

    question_id: OpaqueId
    question_version: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    answer: Answer
    supersedes_submission_id: OpaqueId | None = None


class Submission(ApiModel):
    model_config = ConfigDict(frozen=True)

    submission_id: OpaqueId
    session_id: OpaqueId
    question_id: OpaqueId
    question_version: str
    answer: Answer
    supersedes_submission_id: OpaqueId | None
    run_id: OpaqueId
    created_at: UtcDatetime


class SubmissionAccepted(ApiModel):
    submission_id: OpaqueId
    run_id: OpaqueId
    status: RunStatus


class CreateMessageRequest(RequestModel):
    """`POST /api/sessions/{id}/messages`."""

    text: Annotated[str, StringConstraints(min_length=1, max_length=4_000)]
    file_ids: list[OpaqueId] = Field(default_factory=list, max_length=5)


class MessageAccepted(ApiModel):
    message_id: OpaqueId
    run_id: OpaqueId
    status: RunStatus


class SubmissionList(ApiModel):
    submissions: list[Submission]
    next_cursor: str | None
