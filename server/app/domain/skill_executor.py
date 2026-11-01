"""The shared agent runtime (CLAUDE.md §2.3): one executor, per-course SubjectPack config.

A Calc BC agent and an APUSH agent differ only in their pack (prompt, skills, rubrics,
content, tools). The executor picks the skill from the Run kind, checks that the skill is
pinned on the Session and that the content versions it was pinned to are still the ones
loaded, and never grades with different content than the session started with.
"""

from __future__ import annotations

from app.domain.ports.content import QuestionContent, SubjectPackRegistry
from app.domain.ports.execution import ExecutionFailure, ExecutionOutput, ExecutionRequest
from app.domain.ports.llm import LlmGateway
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.ports.tools import ToolRunner
from app.domain.skills import rubric_assessment, socratic_guidance
from app.domain.types.run import RunKind


class SkillExecutor:
    def __init__(
        self,
        gateway: LlmGateway,
        registry: SubjectPackRegistry,
        tools: ToolRunner,
        clock: Clock,
        ids: IdFactory,
    ) -> None:
        self._gateway = gateway
        self._registry = registry
        self._tools = tools
        self._clock = clock
        self._ids = ids

    async def execute(self, request: ExecutionRequest) -> ExecutionOutput:
        session = request.session
        pack = self._registry.pack(session.course_id)
        if pack is None:
            raise ExecutionFailure("COURSE_CONTENT_UNAVAILABLE")
        if pack.pack_version != session.context_version.pack or (
            pack.workflow_version != session.context_version.workflow
        ):
            # Pinned versions changed under an open session: do not silently switch.
            raise ExecutionFailure("CONTENT_VERSION_CHANGED")
        question: QuestionContent | None = None
        if session.activity is not None:
            question = self._registry.question(session.course_id, session.activity.question_id)
            if question is None or question.version != session.activity.question_version:
                raise ExecutionFailure("CONTENT_VERSION_CHANGED")

        if request.run.kind is RunKind.HINT:
            if socratic_guidance.SKILL not in session.agent_skills:
                raise ExecutionFailure("SKILL_NOT_ENABLED")
            return await socratic_guidance.run_socratic_guidance(
                self._gateway, self._registry, pack, request, question
            )

        if request.run.kind is RunKind.ASSESS_SUBMISSION:
            if rubric_assessment.SKILL not in session.agent_skills:
                raise ExecutionFailure("SKILL_NOT_ENABLED")
            submission = request.submission
            if submission is None:
                raise ExecutionFailure("SUBMISSION_NOT_FOUND")
            if question is None or question.question_id != submission.question_id:
                question = self._registry.question(session.course_id, submission.question_id)
            if question is None or question.version != submission.question_version:
                raise ExecutionFailure("CONTENT_VERSION_CHANGED")
            rubric = self._registry.rubric(
                session.course_id, question.rubric_id, question.rubric_version
            )
            if rubric is None:
                raise ExecutionFailure("COURSE_CONTENT_UNAVAILABLE")
            return await rubric_assessment.run_rubric_assessment(
                self._gateway, self._tools, self._clock, self._ids,
                pack, request, question, rubric, submission,
            )  # fmt: skip

        raise ExecutionFailure("UNSUPPORTED_RUN_KIND")
