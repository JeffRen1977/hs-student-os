"""The contract of a platform ability (Step 44; the catalog fields of Step 23.1).

A course package selects abilities by ID and supplies data; it never supplies a handler.
Each ability declares what it handles and what package data it needs, so the executor and
the package validator read those facts instead of naming abilities in `if` branches.

Adding a Run kind or a question shape is a contract change, made here and in the domain
types; adding an ability that uses existing ones touches only its module and the catalog.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from app.domain.ports.content import (
    ModelTier,
    PackContent,
    QuestionContent,
    RubricContent,
    SubjectPackRegistry,
)
from app.domain.ports.execution import ExecutionFailure, ExecutionOutput, ExecutionRequest
from app.domain.ports.llm import LlmGateway
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.ports.tools import ToolRunner
from app.domain.types.run import RunKind
from app.domain.types.submission import Submission


class QuestionShape(StrEnum):
    NONE = "none"  # the Run has no question, e.g. open tutoring chat
    CHOICE_SET = "choice-set"
    SOURCED = "sourced"
    FREE_RESPONSE = "free-response"


class AbilityEvidence(StrEnum):
    HINT_USAGE = "hint-usage"  # never independent evidence (CLAUDE.md §6.3)
    RUBRIC_CRITERIA = "rubric-criteria"
    ANSWER_KEY = "answer-key"


class ShapedQuestion(Protocol):
    """Satisfied by both the runtime question and the package schema's question."""

    @property
    def items(self) -> Sequence[Any] | None: ...

    @property
    def source_material_ids(self) -> Sequence[str]: ...


def question_shape(question: ShapedQuestion | None) -> QuestionShape:
    if question is None:
        return QuestionShape.NONE
    if question.items is not None:
        return QuestionShape.CHOICE_SET
    if question.source_material_ids:
        return QuestionShape.SOURCED
    return QuestionShape.FREE_RESPONSE


@dataclass(frozen=True, slots=True, kw_only=True)
class AbilityContext:
    """Everything a handler may use: the pinned package's data and the platform's ports."""

    packs: SubjectPackRegistry
    tools: ToolRunner
    clock: Clock
    ids: IdFactory
    gateway: LlmGateway | None
    pack: PackContent
    request: ExecutionRequest
    question: QuestionContent | None

    @property
    def model(self) -> LlmGateway:
        assert self.gateway is not None, "the executor only runs needs_model abilities with one"
        return self.gateway

    def assessment_inputs(self) -> tuple[QuestionContent, RubricContent, Submission]:
        """The checked question and submission of an assessment Run, with its pinned rubric."""
        session, question, submission = self.request.session, self.question, self.request.submission
        assert question is not None and submission is not None
        rubric = self.packs.rubric(
            session.course_id, question.rubric_id, question.rubric_version, self.pack.pack_version
        )
        if rubric is None:
            raise ExecutionFailure("COURSE_CONTENT_UNAVAILABLE")
        return question, rubric, submission


AbilityHandler = Callable[[AbilityContext], Awaitable[ExecutionOutput]]


@dataclass(frozen=True, slots=True, kw_only=True)
class AbilityDataRule:
    """The package data an ability grades, checked in both directions by the validator."""

    shape: QuestionShape
    missing_ability: str  # why a question of this shape needs the ability
    missing_data: str  # why the ability needs a question of this shape
    issue_path_suffix: str = ""
    # Bundled first-party packs predate this rule for free-response questions.
    enforced_on_bundled: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class AbilityDefinition:
    ability_id: str
    version: str  # bump when grading behavior changes; open Sessions keep the old one
    run_kinds: frozenset[RunKind]
    question_shapes: frozenset[QuestionShape]
    needs_model: bool
    model_tier_floor: ModelTier | None
    evidence: AbilityEvidence
    handler: AbilityHandler
    data_rule: AbilityDataRule | None = None
    settings: frozenset[str] = frozenset()  # package-configurable settings; none today
