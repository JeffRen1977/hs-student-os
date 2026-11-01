"""Choice sets scored by the server: the `choice-scoring` platform ability.

Any course package can use it. Multiple-choice items have a key, so scoring them with a
model would only add a way to be wrong. This ability parses the student's choices, scores
each item against its key, and hands an ordinary `AssessmentDraft` to the same
AssessmentService as rubric grading, so evidence, mastery and events follow the one commit
path. Rubric points from a short set are never turned into an exam score.

Answer format (what the web client sends): one line per item, e.g. `1: B`. `1. b`,
`1) B` and `Item 1 - B` are accepted too. A missing, repeated or unreadable item makes
the whole answer `insufficient_evidence`: nothing is recorded as evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.ports.content import PackContent, QuestionContent, RubricContent
from app.domain.ports.execution import ExecutionOutput
from app.domain.types.assessment import (
    AssessmentStatus,
    RubricResult,
    Uncertainty,
    UncertaintyLevel,
)
from app.domain.types.assessment_draft import AssessmentDraft
from app.domain.types.submission import Submission

SKILL = "choice-scoring"
SCORER_VERSION = "rule:choice-scoring-v1"
_LINE = re.compile(
    r"^[ \t]*(?:item[ \t]*)?(?P<item>\d{1,2})[ \t]*[:.)\-][ \t]*\(?(?P<choice>[A-Da-d])\)?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ParsedChoice:
    choice: str
    start: int
    end: int


def parse_choices(text: str) -> dict[str, ParsedChoice] | None:
    """item id → the chosen key and its span; None if an item is given twice."""
    found: dict[str, ParsedChoice] = {}
    for m in _LINE.finditer(text):
        item = str(int(m["item"]))
        if item in found:
            return None
        found[item] = ParsedChoice(choice=m["choice"].upper(), start=m.start(), end=m.end())
    return found


def is_choice_set(question: QuestionContent | None) -> bool:
    return question is not None and question.items is not None


def score_choice_set(
    pack: PackContent,
    question: QuestionContent,
    rubric: RubricContent,
    submission: Submission,
) -> ExecutionOutput:
    assert question.items is not None
    base = {
        "submission_id": submission.submission_id,
        "question_id": question.question_id,
        "question_version": question.version,
        "rubric_id": rubric.rubric_id,
        "rubric_version": rubric.version,
        "workflow_version": pack.workflow_version,
        "model_version": SCORER_VERSION,
    }
    parsed = parse_choices(submission.answer.text)
    expected = {i.item_id for i in question.items}
    if parsed is None or set(parsed) != expected:
        text = (
            "I couldn't read one answer per item. Answer every item with one letter, "
            "one item per line (for example `1: B`)."
        )
        return ExecutionOutput(
            agent_text=text,
            model_version=SCORER_VERSION,
            synthetic=False,
            assessment=AssessmentDraft(
                **base,
                status=AssessmentStatus.INSUFFICIENT_EVIDENCE,
                rubric_results=tuple(
                    RubricResult(criterion_id=c.criterion_id, earned=0, possible=c.max_points)
                    for c in rubric.criteria
                ),
                uncertainty=Uncertainty(
                    level=UncertaintyLevel.HIGH, reasons=("answers_not_readable",)
                ),
                feedback=text,
            ),
        )

    limits = {c.criterion_id: c.max_points for c in rubric.criteria}
    by_criterion: dict[str, RubricResult] = {}
    lines: list[str] = []
    for item in question.items:
        got = parsed[item.item_id]
        right = got.choice == item.answer_key
        by_criterion[item.criterion_id] = RubricResult(
            criterion_id=item.criterion_id,
            earned=limits[item.criterion_id] if right else 0,
            possible=limits[item.criterion_id],
            evidence_refs=(f"{submission.submission_id}:text:{got.start}-{got.end}",),
        )
        lines.append(f"Item {item.item_id}: {'correct' if right else 'not correct'}.")
    feedback = " ".join(lines)
    return ExecutionOutput(
        agent_text=feedback,
        model_version=SCORER_VERSION,
        synthetic=False,
        assessment=AssessmentDraft(
            **base,
            status=AssessmentStatus.ACCEPTED,
            rubric_results=tuple(by_criterion[c.criterion_id] for c in rubric.criteria),
            uncertainty=Uncertainty(level=UncertaintyLevel.LOW, reasons=("scored_by_key",)),
            feedback=feedback,
        ),
    )
