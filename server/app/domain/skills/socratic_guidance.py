"""Socratic guidance: answer a student message with a hint that guides without solving.

Every reply from this skill is a server-issued hint. The run worker records it on the
Session (`server_hint_count`) so later assessments know the work was assisted.
"""

from __future__ import annotations

from typing import Any

from app.domain.context_loader import (
    conversation,
    materials_block,
    render_system_prompt,
    retrieve_materials,
)
from app.domain.ports.content import PackContent, QuestionContent, SubjectPackRegistry
from app.domain.ports.execution import ExecutionFailure, ExecutionOutput, ExecutionRequest
from app.domain.ports.llm import BudgetContext, Effort, LlmGateway, LlmRequest

SKILL = "socratic-guidance"
MAX_REPLY_CHARS = 4000
MAX_OUTPUT_TOKENS = 1500

INSTRUCTIONS = """## Skill: Socratic guidance
- Reply to the student's latest message with one focused hint or question.
- Do not state the final answer or complete the remaining steps for them.
- If the student's work has an error, point to the step and ask a question about it.
- Keep it short (at most a few sentences) and use standard notation.
- Return JSON: {"reply": "<your message to the student>"}."""

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"reply": {"type": "string"}},
    "required": ["reply"],
    "additionalProperties": False,
}


def parse_reply(data: Any) -> str:
    if not isinstance(data, dict) or set(data) != {"reply"}:
        raise ValueError("expected {reply}")
    reply = data["reply"]
    if not isinstance(reply, str) or not reply.strip():
        raise ValueError("reply must be non-empty text")
    if len(reply) > MAX_REPLY_CHARS:
        raise ValueError("reply too long")
    return reply.strip()


def question_block(question: QuestionContent | None) -> str:
    if question is None:
        return "## Current activity\nOpen study conversation (no specific question)."
    return f"## Current activity\nTopic: {question.topic}\nQuestion: {question.prompt}"


async def run_socratic_guidance(
    gateway: LlmGateway,
    registry: SubjectPackRegistry,
    pack: PackContent,
    request: ExecutionRequest,
    question: QuestionContent | None,
) -> ExecutionOutput:
    history = conversation(request.history, pack.context_budget_tokens)
    if not history:
        raise ExecutionFailure("NO_STUDENT_MESSAGE")
    skill_ids = question.skill_ids if question else tuple(pack.skill_names)
    retrieval = retrieve_materials(
        registry,
        student_id=request.session.student_id,
        course_id=pack.course_id,
        skill_ids=skill_ids,
    )
    system = "\n\n".join(
        (
            render_system_prompt(pack, request),
            INSTRUCTIONS,
            question_block(question),
            materials_block(retrieval),
        )
    )
    result = await gateway.generate(
        LlmRequest(
            purpose=SKILL,
            pack_tier=pack.model_tier,
            workflow_version=pack.workflow_version,
            system=system,
            messages=history,
            output_schema=OUTPUT_SCHEMA,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            effort=Effort.LOW,
            budget=BudgetContext(
                student_id=request.session.student_id,
                session_id=request.session.session_id,
                run_id=request.run.run_id,
            ),
        ),
        parse_reply,
    )
    return ExecutionOutput(
        agent_text=result.value,
        model_version=result.model_version,
        synthetic=False,
        issued_hint=True,
        usage_tokens=result.usage.total,
    )
