"""Admissions workspace API (Step 35, API.md §6.5)."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator

from app.domain.types.run import RunStatus
from app.schemas.common import ApiModel, OpaqueId, RequestModel, UtcDatetime

Category = Literal["activity", "achievement", "experience", "value", "goal", "background"]
Short = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class InterviewPromptView(ApiModel):
    prompt_id: str
    category: Category
    text: str


class InterviewPromptList(ApiModel):
    prompt_set_version: str
    prompts: list[InterviewPromptView]


class InterviewAnswerRequest(RequestModel):
    prompt_id: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    text: Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class QueuedView(ApiModel):
    run_id: OpaqueId
    status: RunStatus


class InterviewAnswerView(ApiModel):
    answer_id: OpaqueId
    prompt_id: str
    prompt_set_version: str
    text: str
    run_id: OpaqueId
    created_at: UtcDatetime


class InterviewAnswerAccepted(InterviewAnswerView):
    run: QueuedView


class InterviewAnswerList(ApiModel):
    answers: list[InterviewAnswerView]


class FactView(ApiModel):
    fact_id: OpaqueId
    text: str
    category: Category
    status: Literal["proposed", "confirmed", "rejected"]
    source: Literal["interview", "student"]
    answer_id: OpaqueId | None
    quote: str | None  # the student's own words a proposal rests on
    created_at: UtcDatetime
    decided_at: UtcDatetime | None
    version: int


class FactList(ApiModel):
    facts: list[FactView]


class AddFactRequest(RequestModel):
    text: Short
    category: Category


class ConfirmFactRequest(RequestModel):
    text: Short | None = None  # reword in your own words when confirming


class ActivityRequest(RequestModel):
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    role: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    description: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    hours_per_week: int = Field(ge=0, le=80)
    weeks_per_year: int = Field(ge=0, le=52)
    fact_ids: list[OpaqueId] = Field(default_factory=list, max_length=10)
    # The student confirms the entry is accurate (Step 35.4). Saving without it is refused.
    student_confirmed: bool


class ActivityView(ApiModel):
    activity_id: OpaqueId
    name: str
    role: str
    description: str
    hours_per_week: int
    weeks_per_year: int
    fact_ids: list[OpaqueId]
    confirmed_at: UtcDatetime
    updated_at: UtcDatetime
    version: int


class ActivityList(ApiModel):
    activities: list[ActivityView]


class DeadlineRequest(RequestModel):
    school: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    kind: Literal[
        "early_decision", "early_action", "restrictive_early_action", "regular",
        "rolling", "scholarship", "financial_aid", "other",
    ]  # fmt: skip
    due_date: dt.date
    source_url: Annotated[str, StringConstraints(max_length=500)] | None = None
    source_checked_on: dt.date | None = None
    notes: Annotated[str, StringConstraints(max_length=500)] = ""

    @field_validator("source_url")
    @classmethod
    def _https(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("https://"):
            raise ValueError("sourceUrl must be an https:// link to the school's page")
        return v


class DeadlineView(ApiModel):
    deadline_id: OpaqueId
    school: str
    kind: str
    due_date: dt.date
    days_left: int
    source_url: str | None
    source_checked_on: dt.date | None
    verification: Literal["verified", "stale", "unverified", "unsourced"]
    uncertainty: str  # what the student should do about the verification status
    notes: str
    version: int


class DeadlineList(ApiModel):
    deadlines: list[DeadlineView]


class CreateEssayRequest(RequestModel):
    title: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    prompt: Annotated[str, StringConstraints(min_length=1, max_length=1500)]


class SaveDraftRequest(RequestModel):
    draft: Annotated[str, StringConstraints(max_length=20_000)]


class EssayView(ApiModel):
    essay_id: OpaqueId
    title: str
    prompt: str
    draft: str
    version: int
    active_run_id: OpaqueId | None
    updated_at: UtcDatetime


class EssayList(ApiModel):
    essays: list[EssayView]


class FeedbackRequestBody(RequestModel):
    kind: Literal["outline", "feedback"]


class FeedbackItemView(ApiModel):
    type: Literal["outline_point", "strength", "question", "suggestion"]
    text: str
    fact_ids: list[OpaqueId]


class FeedbackView(ApiModel):
    feedback_id: OpaqueId
    essay_id: OpaqueId
    essay_version: int
    kind: Literal["outline", "feedback"]
    run_id: OpaqueId
    items: list[FeedbackItemView]  # empty until the run succeeds
    created_at: UtcDatetime
    completed_at: UtcDatetime | None


class FeedbackAccepted(FeedbackView):
    run: QueuedView


class FeedbackList(ApiModel):
    feedback: list[FeedbackView]
