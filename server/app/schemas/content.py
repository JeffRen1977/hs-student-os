"""Schemas for versioned, reviewable content: packs, questions, rubrics, mappings.

Content lives in `server/content/` and is loaded by `app.registries.content`.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from app.domain.types.common import AgentType, Availability, StudyMode, TaskType
from app.domain.types.course import CourseCategory
from app.schemas.common import ApiModel, CourseId, OpaqueId, SemVer, SkillId

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9\-]*$")]
NonEmpty = Annotated[str, StringConstraints(min_length=1)]


class Review(ApiModel):
    """Human review state. Content is `draft` until a named content reviewer signs off."""

    status: Literal["draft", "reviewed"]
    reviewer: NonEmpty | None = None
    reviewed_at: date | None = None

    @model_validator(mode="after")
    def _reviewed_needs_reviewer(self) -> Self:
        if self.status == "reviewed" and (self.reviewer is None or self.reviewed_at is None):
            raise ValueError("reviewed content requires reviewer and reviewedAt")
        if self.status == "draft" and self.reviewer is not None:
            raise ValueError("draft content has no reviewer yet")
        return self


class ContentSource(ApiModel):
    type: Literal["original", "licensed"]
    author: NonEmpty
    license: NonEmpty

    @model_validator(mode="after")
    def _no_unlicensed_official_material(self) -> Self:
        if "college board" in self.author.lower() and self.type != "licensed":
            raise ValueError("College Board material requires an explicit license")
        return self


class PackManifest(ApiModel):
    course_id: CourseId
    name: NonEmpty
    description: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    category: CourseCategory
    version: SemVer
    availability: Availability
    agent_type: AgentType
    supported_task_types: list[TaskType]
    supported_modes: list[StudyMode]
    skills: list[Slug] = Field(default_factory=list)
    tools: list[Slug] = Field(default_factory=list)
    model_tier: Literal["fast", "balanced", "strong"] | None = None
    context_budget_tokens: int = Field(default=8000, ge=1000, le=200_000)
    system_prompt_path: str | None = None
    # Pinned on every Session (contextVersion.workflow) so results trace to a workflow.
    workflow_version: Slug | None = None

    @model_validator(mode="after")
    def _active_packs_are_complete(self) -> Self:
        if self.availability is Availability.ACTIVE:
            missing = [
                name
                for name, value in (
                    ("supportedTaskTypes", self.supported_task_types),
                    ("supportedModes", self.supported_modes),
                    ("skills", self.skills),
                    ("modelTier", self.model_tier),
                    ("systemPromptPath", self.system_prompt_path),
                    ("workflowVersion", self.workflow_version),
                )
                if not value
            ]
            if missing:
                raise ValueError("active packs require: " + ", ".join(missing))
        return self


class SkillDefinition(ApiModel):
    skill_id: SkillId
    name: NonEmpty
    description: NonEmpty


class SkillCatalog(ApiModel):
    course_id: CourseId
    version: SemVer
    skills: list[SkillDefinition] = Field(min_length=1)


class RubricRef(ApiModel):
    rubric_id: Slug
    version: NonEmpty


class AnswerCheck(ApiModel):
    """A closed-form final answer the math-verify tool can check (SymPy syntax)."""

    tool: Literal["math-verify"]
    criterion_id: Slug
    expression: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    variables: list[Annotated[str, StringConstraints(pattern=r"^[a-z]$")]] = Field(min_length=1)


ChoiceKey = Literal["A", "B", "C", "D"]


class Choice(ApiModel):
    key: ChoiceKey
    text: NonEmpty


class ChoiceItem(ApiModel):
    """One multiple-choice item of a choice set. Scored by the server, not a model.

    `answerKey` never leaves the server: the session activity projection drops it.
    """

    item_id: Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]?$")]
    prompt: NonEmpty
    choices: list[Choice] = Field(min_length=2, max_length=4)
    answer_key: ChoiceKey
    criterion_id: Slug

    @model_validator(mode="after")
    def _key_is_a_choice(self) -> Self:
        keys = [c.key for c in self.choices]
        if len(keys) != len(set(keys)) or self.answer_key not in keys:
            raise ValueError("choices need unique keys and must include the answerKey")
        return self


class Question(ApiModel):
    question_id: OpaqueId
    version: NonEmpty
    course_id: CourseId
    topic: NonEmpty
    skill_ids: list[SkillId] = Field(min_length=1)
    difficulty: Literal["easy", "medium", "hard"]
    prompt: NonEmpty
    expected_answer: NonEmpty
    rubric_ref: RubricRef
    answer_check: AnswerCheck | None = None
    # Choice sets: multiple-choice items scored deterministically (choice-scoring).
    items: list[ChoiceItem] | None = Field(default=None, min_length=1, max_length=10)
    source: ContentSource
    review: Review

    @model_validator(mode="after")
    def _choice_sets_are_consistent(self) -> Self:
        if self.items is not None:
            ids = [i.item_id for i in self.items]
            if len(ids) != len(set(ids)):
                raise ValueError("itemId values must be unique")
            if self.answer_check is not None:
                raise ValueError("choice sets are scored by key, not by math-verify")
        return self


class Material(ApiModel):
    """A short reviewed passage the agent may cite (RAG v1, BACKEND.md §7)."""

    material_id: OpaqueId
    version: NonEmpty
    course_id: CourseId
    skill_ids: list[SkillId] = Field(min_length=1)
    title: NonEmpty
    text: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    source: ContentSource
    review: Review


class RubricCriterion(ApiModel):
    criterion_id: Slug
    description: NonEmpty
    max_points: int = Field(ge=1, le=10)
    evidence_requirements: list[NonEmpty] = Field(min_length=1)
    skill_ids: list[SkillId] = Field(min_length=1)


class Rubric(ApiModel):
    rubric_id: Slug
    version: NonEmpty
    course_id: CourseId
    criteria: list[RubricCriterion] = Field(min_length=1)
    source: ContentSource
    review: Review

    @model_validator(mode="after")
    def _unique_criteria(self) -> Self:
        ids = [c.criterion_id for c in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("criterionId values must be unique within a rubric")
        return self

    @property
    def max_points(self) -> int:
        return sum(c.max_points for c in self.criteria)
