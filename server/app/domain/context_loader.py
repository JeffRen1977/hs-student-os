"""Assemble the minimal, course-scoped context for one model call (BACKEND.md §5.4, Step 17.5).

System prompt order: SubjectPack prompt (interpolated) → skill instructions → student
context summary → question/rubric (assessment only) → reviewed reference material.

Only this session's messages are loaded; other courses' conversations never are. Material
retrieval is deterministic over a small reviewed corpus and filtered by course and owner
*before* matching; when nothing relevant exists the result says so (material not found)
rather than letting the model invent a source.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.ports.content import MaterialContent, PackContent, SubjectPackRegistry
from app.domain.ports.execution import ExecutionRequest
from app.domain.ports.llm import LlmMessage, LlmRole
from app.domain.types.message import Message, MessageRole

CHARS_PER_TOKEN = 4
MAX_MATERIALS = 2


@dataclass(frozen=True, slots=True, kw_only=True)
class Retrieval:
    materials: Sequence[MaterialContent]

    @property
    def found(self) -> bool:
        return bool(self.materials)


def retrieve_materials(
    registry: SubjectPackRegistry, *, student_id: str, course_id: str, skill_ids: Sequence[str]
) -> Retrieval:
    candidates = [
        m
        for m in registry.materials(course_id)
        # ACL first: course material, or this student's own; never another course/student.
        if m.course_id == course_id and m.student_id in (None, student_id)
    ]
    wanted = set(skill_ids)
    scored = sorted(
        ((len(wanted & set(m.skill_ids)), m.material_id, m) for m in candidates),
        key=lambda t: (-t[0], t[1]),
    )
    return Retrieval(materials=tuple(m for score, _, m in scored if score > 0)[:MAX_MATERIALS])


def render_system_prompt(pack: PackContent, request: ExecutionRequest) -> str:
    """Fill the pack template's variables. Student data enters only through these slots."""
    values = {
        "studentName": request.student_name or "the student",
        "currentMode": request.mode or "practice",
        "masteryContext": request.mastery_context or "No mastery evidence recorded yet.",
    }
    prompt = pack.system_prompt
    for key, value in values.items():
        prompt = prompt.replace("{{" + key + "}}", value)
    return prompt


def materials_block(retrieval: Retrieval) -> str:
    if not retrieval.found:
        return (
            "## Reference material\nMATERIAL_NOT_FOUND: no reviewed material covers this topic. "
            "Do not cite or invent sources."
        )
    parts = ["## Reference material (reviewed; cite by source reference if used)"]
    for m in retrieval.materials:
        parts.append(f"### {m.title} [source: {m.source_ref}]\n{m.text}")
    return "\n\n".join(parts)


def conversation(history: Sequence[Message], budget_tokens: int) -> list[LlmMessage]:
    """Session messages oldest → newest, truncated from the oldest end to fit the budget.

    Synthetic (test-pipeline) replies are excluded: they are not tutoring.
    """
    usable = [m for m in history if not m.synthetic and m.text.strip()]
    kept: list[Message] = []
    used = 0
    for m in reversed(usable):
        cost = len(m.text) // CHARS_PER_TOKEN + 4
        if kept and used + cost > budget_tokens:
            break
        kept.append(m)
        used += cost
    kept.reverse()
    while kept and kept[0].role is not MessageRole.STUDENT:
        kept.pop(0)  # the model conversation must start with the student
    return [
        LlmMessage(
            role=LlmRole.USER if m.role is MessageRole.STUDENT else LlmRole.ASSISTANT,
            text=m.text,
        )
        for m in kept
    ]
