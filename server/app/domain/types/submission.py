from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class SubmissionAnswer:
    text: str
    file_ids: Sequence[str] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class SubmissionInput:
    """What the student sends. Contains no score, status, or evidence claims."""

    question_id: str
    question_version: str
    answer: SubmissionAnswer
    supersedes_submission_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Submission:
    """Immutable once stored. A correction is a new Submission that supersedes this one."""

    submission_id: str
    student_id: str
    session_id: str
    question_id: str
    question_version: str
    answer: SubmissionAnswer
    supersedes_submission_id: str | None
    run_id: str
    created_at: datetime
    # Server records captured when the submission was accepted (never client-provided):
    # hints issued earlier in the session, and earlier attempts at the same question.
    server_hint_count: int = 0
    prior_attempt_count: int = 0

    @property
    def is_assisted(self) -> bool:
        """Hint-assisted or a correction after feedback: never independent evidence."""
        return self.server_hint_count > 0 or self.prior_attempt_count > 0
