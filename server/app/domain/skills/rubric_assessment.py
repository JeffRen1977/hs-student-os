"""Rubric assessment of one submission against its pinned rubric version (Step 17.3).

The model scores each rubric criterion and quotes the parts of the student's answer that
support it. The server then:
- locates every quote in the stored answer and turns it into an evidence reference
  (`{submissionId}:text:{start}-{end}`); points without locatable evidence are rejected;
- checks the closed-form final answer with math-verify when the question has one; a
  verifier/model disagreement downgrades the result to insufficient_evidence, and an
  unavailable verifier is recorded as such (never as a verified answer);
- leaves skill evidence and hint usage to AssessmentService, which derives them from the
  rubric and the server's own hint records.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.domain.context_loader import render_system_prompt
from app.domain.ports.content import PackContent, QuestionContent, RubricContent
from app.domain.ports.execution import ExecutionOutput, ExecutionRequest
from app.domain.ports.llm import BudgetContext, Effort, LlmGateway, LlmMessage, LlmRequest, LlmRole
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.ports.tools import ToolContext, ToolNotAllowedError, ToolRunner
from app.domain.types.assessment import (
    AssessmentStatus,
    RubricResult,
    Uncertainty,
    UncertaintyLevel,
)
from app.domain.types.assessment_draft import AssessmentDraft
from app.domain.types.submission import Submission
from app.domain.types.tool import ToolResult, ToolStatus

SKILL = "rubric-assessment"
MAX_OUTPUT_TOKENS = 4000
MAX_FEEDBACK_CHARS = 2000
LIMITED_FEEDBACK_CHARS = 600
MAX_REASONS = 6
_LEVEL_ORDER = (UncertaintyLevel.LOW, UncertaintyLevel.LIMITED, UncertaintyLevel.HIGH)

INSTRUCTIONS = """## Skill: Rubric assessment
You are grading one student answer against a fixed rubric. Grade only what the student
wrote; do not credit steps that are not shown.
- Score every rubric criterion exactly once, from 0 to its maximum points.
- assessable: false when a criterion cannot be judged on its own, because it only failed
  as a consequence of an earlier error or the student never reached that step; its
  earned must be 0. Use true whenever the student's own work on that step can be judged.
- For each point you award, copy one or more EXACT substrings of the student's answer that
  support it into evidenceQuotes (character-for-character, no paraphrase).
- Use status "insufficient_evidence" when the answer does not show enough work to judge the
  skills (for example a bare final answer, an off-topic answer, or ambiguous reasoning).
- finalExpression: the student's final answer rewritten in SymPy syntax using only the
  question's variables (for example 3*x**2*cos(x**3 + 1)), or "" if there is none.
- uncertainty: how confident the grading is (low, limited, high), with short snake_case
  reason codes.
- feedback: 2-5 sentences to the student naming what was right and the specific step to
  revisit. Do not reveal a complete solution. Never mention scores or exam predictions.
Return only the JSON object."""


def output_schema(rubric: RubricContent) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["accepted", "insufficient_evidence"]},
            "statusReasons": {"type": "array", "items": {"type": "string"}},
            "criteria": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "criterionId": {
                            "type": "string",
                            "enum": [c.criterion_id for c in rubric.criteria],
                        },
                        "earned": {"type": "integer"},
                        "assessable": {"type": "boolean"},
                        "evidenceQuotes": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["criterionId", "earned", "assessable", "evidenceQuotes"],
                    "additionalProperties": False,
                },
            },
            "finalExpression": {"type": "string"},
            "uncertainty": {"type": "string", "enum": ["low", "limited", "high"]},
            "uncertaintyReasons": {"type": "array", "items": {"type": "string"}},
            "feedback": {"type": "string"},
        },
        "required": [
            "status", "statusReasons", "criteria", "finalExpression",
            "uncertainty", "uncertaintyReasons", "feedback",
        ],
        "additionalProperties": False,
    }  # fmt: skip


def reason_code(text: str) -> str:
    code = re.sub(r"[^a-z0-9_]+", "_", text.strip().lower()).strip("_")
    return code[:64] or "unspecified"


def raise_level(level: UncertaintyLevel, at_least: UncertaintyLevel) -> UncertaintyLevel:
    return max(level, at_least, key=_LEVEL_ORDER.index)


@dataclass(frozen=True, slots=True, kw_only=True)
class GradedAnswer:
    status: AssessmentStatus
    reasons: tuple[str, ...]
    rubric_results: tuple[RubricResult, ...]
    final_expression: str
    uncertainty: UncertaintyLevel
    uncertainty_reasons: tuple[str, ...]
    feedback: str


def make_parser(rubric: RubricContent, submission: Submission) -> Any:
    answer = submission.answer.text
    limits = {c.criterion_id: c.max_points for c in rubric.criteria}

    def locate(quote: str) -> str | None:
        quote = quote.strip()
        start = answer.find(quote) if quote else -1
        if start < 0:
            return None
        return f"{submission.submission_id}:text:{start}-{start + len(quote)}"

    def parse(data: Any) -> GradedAnswer:
        if not isinstance(data, dict):
            raise ValueError("expected an object")
        criteria = data["criteria"]
        if not isinstance(criteria, list):
            raise ValueError("criteria must be a list")
        seen: dict[str, RubricResult] = {}
        for item in criteria:
            cid, earned = item["criterionId"], item["earned"]
            if cid not in limits or cid in seen:
                raise ValueError("unknown or repeated criterion")
            if not isinstance(earned, int) or isinstance(earned, bool):
                raise ValueError("earned must be an integer")
            if not 0 <= earned <= limits[cid]:
                raise ValueError("earned out of range")
            assessable = item["assessable"]
            if not isinstance(assessable, bool) or (earned and not assessable):
                raise ValueError("unassessable criteria earn no points")
            refs = [r for q in item["evidenceQuotes"] if isinstance(q, str) and (r := locate(q))]
            if earned > 0 and not refs:
                raise ValueError("awarded points need evidence quoted from the answer")
            seen[cid] = RubricResult(
                criterion_id=cid,
                earned=earned,
                possible=limits[cid],
                evidence_refs=tuple(dict.fromkeys(refs)),
                assessable=assessable,
            )
        if set(seen) != set(limits):
            raise ValueError("every criterion must be scored")
        feedback = data["feedback"]
        if not isinstance(feedback, str) or not feedback.strip():
            raise ValueError("feedback required")
        final = data["finalExpression"]
        if not isinstance(final, str):
            raise ValueError("finalExpression must be text")
        return GradedAnswer(
            status=AssessmentStatus(data["status"]),
            reasons=tuple(reason_code(str(r)) for r in data["statusReasons"])[:MAX_REASONS],
            rubric_results=tuple(seen[c.criterion_id] for c in rubric.criteria),
            final_expression=final.strip(),
            uncertainty=UncertaintyLevel(data["uncertainty"]),
            uncertainty_reasons=tuple(reason_code(str(r)) for r in data["uncertaintyReasons"])[
                :MAX_REASONS
            ],
            feedback=feedback.strip()[:MAX_FEEDBACK_CHARS],
        )

    return parse


def rubric_block(question: QuestionContent, rubric: RubricContent) -> str:
    lines = [
        f"## Question {question.question_id} (version {question.version})",
        question.prompt,
        f"## Rubric {rubric.rubric_id} (version {rubric.version})",
    ]
    for c in rubric.criteria:
        reqs = "; ".join(c.evidence_requirements)
        lines.append(f"- {c.criterion_id} (max {c.max_points}): {c.description} Evidence: {reqs}")
    return "\n".join(lines)


def assisted_reasons(submission: Submission) -> tuple[str, ...]:
    reasons: list[str] = []
    if submission.server_hint_count > 0:
        reasons.append("hint_assisted")
    if submission.prior_attempt_count > 0:
        reasons.append("correction_after_feedback")
    return tuple(reasons)


@dataclass(frozen=True, slots=True, kw_only=True)
class VerificationEffect:
    status: AssessmentStatus
    uncertainty: UncertaintyLevel
    reasons: tuple[str, ...]


def apply_verification(
    graded: GradedAnswer, question: QuestionContent, outcome_status: ToolStatus | None,
    equivalent: bool | None,
) -> VerificationEffect:  # fmt: skip
    """How a math-verify result changes the grade. Pure, so it is unit-testable."""
    status, level, reasons = graded.status, graded.uncertainty, ()
    check = question.answer_check
    if check is None or outcome_status is None:
        return VerificationEffect(status=status, uncertainty=level, reasons=reasons)
    if outcome_status is not ToolStatus.OK or equivalent is None:
        return VerificationEffect(
            status=status,
            uncertainty=raise_level(level, UncertaintyLevel.LIMITED),
            reasons=("math_verification_unavailable",),
        )
    result = next(r for r in graded.rubric_results if r.criterion_id == check.criterion_id)
    model_full, model_none = result.earned == result.possible, result.earned == 0
    if (equivalent and model_none) or (not equivalent and model_full):
        return VerificationEffect(
            status=AssessmentStatus.INSUFFICIENT_EVIDENCE,
            uncertainty=UncertaintyLevel.HIGH,
            reasons=("verifier_disagreement",),
        )
    return VerificationEffect(status=status, uncertainty=level, reasons=("final_answer_verified",))


async def run_rubric_assessment(
    gateway: LlmGateway,
    tools: ToolRunner,
    clock: Clock,
    ids: IdFactory,
    pack: PackContent,
    request: ExecutionRequest,
    question: QuestionContent,
    rubric: RubricContent,
    submission: Submission,
) -> ExecutionOutput:
    assisted = assisted_reasons(submission)
    draft_base = {
        "submission_id": submission.submission_id,
        "question_id": question.question_id,
        "question_version": question.version,
        "rubric_id": rubric.rubric_id,
        "rubric_version": rubric.version,
        "workflow_version": pack.workflow_version,
    }
    if not submission.answer.text.strip():
        # Nothing to grade: no model call, no evidence.
        return ExecutionOutput(
            agent_text="I couldn't find any written work in that submission, so there is "
            "nothing to assess yet. Try writing out your steps.",
            model_version="none",
            synthetic=False,
            assessment=AssessmentDraft(
                **draft_base,
                status=AssessmentStatus.INSUFFICIENT_EVIDENCE,
                rubric_results=tuple(
                    RubricResult(criterion_id=c.criterion_id, earned=0, possible=c.max_points)
                    for c in rubric.criteria
                ),
                uncertainty=Uncertainty(level=UncertaintyLevel.HIGH, reasons=("empty_answer",)),
                feedback="No written work was submitted.",
                model_version="none",
            ),
        )

    facts = [f"Server record: the student received {submission.server_hint_count} hint(s) "
             "in this session before submitting."]  # fmt: skip
    if submission.prior_attempt_count:
        facts.append(
            f"This is attempt {submission.prior_attempt_count + 1} at this question, after "
            "feedback on an earlier attempt."
        )
    system = "\n\n".join(
        (render_system_prompt(pack, request), INSTRUCTIONS, rubric_block(question, rubric), *facts)
    )
    result = await gateway.generate(
        LlmRequest(
            purpose=SKILL,
            pack_tier=pack.model_tier,
            workflow_version=pack.workflow_version,
            system=system,
            messages=[
                LlmMessage(
                    role=LlmRole.USER,
                    text="Assess this answer.\n<student_answer>\n"
                    f"{submission.answer.text}\n</student_answer>",
                )
            ],
            output_schema=output_schema(rubric),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            effort=Effort.HIGH,
            budget=BudgetContext(
                student_id=submission.student_id,
                session_id=submission.session_id,
                run_id=request.run.run_id,
            ),
        ),
        make_parser(rubric, submission),
    )
    graded: GradedAnswer = result.value

    tool_results: list[ToolResult] = []
    tool_status: ToolStatus | None = None
    equivalent: bool | None = None
    check = question.answer_check
    if check is not None:
        if graded.final_expression:
            try:
                outcome = await tools.execute(
                    "math-verify",
                    {
                        "expression": graded.final_expression,
                        "expected": check.expression,
                        "variables": list(check.variables),
                    },
                    ToolContext(
                        student_id=submission.student_id,
                        course_id=pack.course_id,
                        run_id=request.run.run_id,
                        skill=SKILL,
                        pack_tools=pack.tools,
                    ),
                )
                tool_status = outcome.status
                raw = outcome.output.get("equivalent")
                equivalent = raw if isinstance(raw, bool) else None
                tool_results.append(
                    ToolResult(
                        tool_result_id=ids.new("tool"),
                        student_id=submission.student_id,
                        run_id=request.run.run_id,
                        tool=outcome.tool,
                        status=outcome.status,
                        output=dict(outcome.output),
                        created_at=clock.now(),
                    )
                )
            except ToolNotAllowedError:
                tool_status = ToolStatus.UNAVAILABLE
        else:
            tool_status = ToolStatus.INVALID_INPUT  # no final answer to verify
    effect = apply_verification(graded, question, tool_status, equivalent)

    level = effect.uncertainty
    if assisted:
        level = raise_level(level, UncertaintyLevel.LIMITED)
    reasons: Sequence[str] = tuple(
        dict.fromkeys((*graded.uncertainty_reasons, *graded.reasons, *effect.reasons, *assisted))
    )[: MAX_REASONS * 2]
    feedback = graded.feedback
    if effect.status is AssessmentStatus.INSUFFICIENT_EVIDENCE:
        feedback = feedback[:LIMITED_FEEDBACK_CHARS]  # limited feedback only
    return ExecutionOutput(
        agent_text=feedback,
        model_version=result.model_version,
        synthetic=False,
        tool_results=tuple(tool_results),
        usage_tokens=result.usage.total,
        assessment=AssessmentDraft(
            **draft_base,
            status=effect.status,
            rubric_results=graded.rubric_results,
            uncertainty=Uncertainty(level=level, reasons=tuple(reasons)),
            feedback=feedback,
            model_version=result.model_version,
            tool_result_ids=tuple(t.tool_result_id for t in tool_results),
        ),
    )
