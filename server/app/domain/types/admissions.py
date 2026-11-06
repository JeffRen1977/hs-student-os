"""Admissions workspace (Step 35): interview → student-confirmed facts → outline and
feedback; sourced deadlines; activities grounded in confirmed facts.

Principles (doc/HIGH_SCHOOL_STUDENT_OS.md, CLAUDE.md §1.3):
- Facts about the student come from the student. A model may *propose* a fact from an
  interview answer, quoting the answer; it is used only after the student confirms it.
- Essay text is the student's. The platform stores drafts the student writes and returns
  outlines and feedback as short, capped items: there is no endpoint that writes an essay.
- A deadline carries its source and when it was last verified; an old or missing
  verification is shown as uncertainty, never as fact.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

FACT_CATEGORIES = ("activity", "achievement", "experience", "value", "goal", "background")
VERIFIED_FOR_DAYS = 30


class FactStatus(StrEnum):
    PROPOSED = "proposed"  # extracted by the model from an answer; not used until confirmed
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class FactSource(StrEnum):
    INTERVIEW = "interview"  # proposed from an interview answer, with a verbatim quote
    STUDENT = "student"  # typed by the student: confirmed on entry


@dataclass(frozen=True, slots=True, kw_only=True)
class InterviewPrompt:
    prompt_id: str
    text: str
    category: str


@dataclass(frozen=True, slots=True, kw_only=True)
class InterviewAnswer:
    answer_id: str
    student_id: str
    prompt_id: str
    prompt_set_version: str
    text: str
    run_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class Fact:
    fact_id: str
    student_id: str
    text: str
    category: str
    status: FactStatus
    source: FactSource
    created_at: datetime
    answer_id: str | None = None
    quote: str | None = None  # verbatim span of the answer the proposal rests on
    decided_at: datetime | None = None
    version: int = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class Activity:
    activity_id: str
    student_id: str
    name: str
    role: str
    description: str
    hours_per_week: int
    weeks_per_year: int
    fact_ids: Sequence[str]
    confirmed_at: datetime  # when the student confirmed the facts this entry rests on
    created_at: datetime
    updated_at: datetime
    version: int = 1


class DeadlineVerification(StrEnum):
    VERIFIED = "verified"  # source checked within VERIFIED_FOR_DAYS
    STALE = "stale"  # source checked, but longer ago: re-check before relying on it
    UNVERIFIED = "unverified"  # source given, never checked
    UNSOURCED = "unsourced"  # no source at all


@dataclass(frozen=True, slots=True, kw_only=True)
class Deadline:
    deadline_id: str
    student_id: str
    school: str
    kind: str  # e.g. early_decision, early_action, regular, scholarship, financial_aid
    due_date: date
    source_url: str | None
    source_checked_on: date | None
    notes: str
    created_at: datetime
    updated_at: datetime
    version: int = 1

    def verification(self, today: date) -> DeadlineVerification:
        if not self.source_url:
            return DeadlineVerification.UNSOURCED
        if self.source_checked_on is None:
            return DeadlineVerification.UNVERIFIED
        if (today - self.source_checked_on).days > VERIFIED_FOR_DAYS:
            return DeadlineVerification.STALE
        return DeadlineVerification.VERIFIED


@dataclass(frozen=True, slots=True, kw_only=True)
class Essay:
    essay_id: str
    student_id: str
    title: str
    prompt: str
    draft: str  # written by the student; the platform never writes or rewrites it
    created_at: datetime
    updated_at: datetime
    version: int = 1
    active_run_id: str | None = None


class FeedbackKind(StrEnum):
    OUTLINE = "outline"  # structure suggestions built only from confirmed facts
    FEEDBACK = "feedback"  # comments on the student's own draft


class FeedbackItemType(StrEnum):
    OUTLINE_POINT = "outline_point"
    STRENGTH = "strength"
    QUESTION = "question"
    SUGGESTION = "suggestion"


@dataclass(frozen=True, slots=True, kw_only=True)
class FeedbackItem:
    type: FeedbackItemType
    text: str
    fact_ids: Sequence[str] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class FeedbackRequest:
    """One requested outline/feedback for one essay version; the run's subject."""

    feedback_id: str
    student_id: str
    essay_id: str
    essay_version: int
    kind: FeedbackKind
    run_id: str
    created_at: datetime
    items: Sequence[FeedbackItem] = ()
    model_version: str | None = None
    completed_at: datetime | None = None
