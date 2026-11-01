"""Read-only, versioned SubjectPack content the skills run against (Step 17.1, 17.5)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from app.domain.types.common import StudyMode


class ModelTier(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    STRONG = "strong"


TIER_ORDER = (ModelTier.FAST, ModelTier.BALANCED, ModelTier.STRONG)


@dataclass(frozen=True, slots=True, kw_only=True)
class CriterionContent:
    criterion_id: str
    description: str
    max_points: int
    evidence_requirements: Sequence[str]
    skill_ids: Sequence[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class RubricContent:
    rubric_id: str
    version: str
    course_id: str
    criteria: Sequence[CriterionContent]


@dataclass(frozen=True, slots=True, kw_only=True)
class AnswerCheck:
    """Closed-form final answer the math-verify tool can compare against."""

    criterion_id: str
    expression: str
    variables: Sequence[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class QuestionContent:
    question_id: str
    version: str
    course_id: str
    topic: str
    prompt: str
    skill_ids: Sequence[str]
    rubric_id: str
    rubric_version: str
    answer_check: AnswerCheck | None = None
    reviewed: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class MaterialContent:
    """A reviewed passage with its source reference (RAG v1: deterministic retrieval)."""

    material_id: str
    course_id: str
    skill_ids: Sequence[str]
    title: str
    text: str
    source_ref: str
    content_hash: str
    student_id: str | None = None  # None = course material; set = a student's own material


@dataclass(frozen=True, slots=True, kw_only=True)
class PackContent:
    course_id: str
    pack_version: str
    workflow_version: str
    system_prompt: str
    model_tier: ModelTier
    context_budget_tokens: int
    tools: Sequence[str]
    skill_names: dict[str, str]  # skillId → display name
    reviewed: bool


class SubjectPackRegistry(Protocol):
    def pack(self, course_id: str) -> PackContent | None:
        """Only active packs are returned; planned packs have no runnable content."""
        ...

    def question(self, course_id: str, question_id: str) -> QuestionContent | None: ...

    def rubric(self, course_id: str, rubric_id: str, version: str) -> RubricContent | None: ...

    def materials(self, course_id: str) -> Sequence[MaterialContent]: ...


MODE_LABELS: dict[StudyMode, str] = {
    StudyMode.GPA_SYNC: "class sync (keep pace with coursework)",
    StudyMode.EXAM_CRUNCH: "exam preparation",
    StudyMode.ADAPTIVE: "adaptive practice",
}
