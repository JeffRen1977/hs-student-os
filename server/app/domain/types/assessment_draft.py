"""What an assessment skill hands to `AssessmentService.commit_assessment`.

It deliberately carries no skill evidence and no hint usage: the service derives both from
the rubric and the server's own records, so a model (or a client) cannot claim them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.types.assessment import AssessmentStatus, RubricResult, Uncertainty


@dataclass(frozen=True, slots=True, kw_only=True)
class AssessmentDraft:
    submission_id: str
    question_id: str
    question_version: str
    rubric_id: str
    rubric_version: str
    status: AssessmentStatus
    rubric_results: Sequence[RubricResult]
    uncertainty: Uncertainty
    feedback: str
    model_version: str
    workflow_version: str
    tool_result_ids: Sequence[str] = ()
    supersedes_assessment_id: str | None = None
