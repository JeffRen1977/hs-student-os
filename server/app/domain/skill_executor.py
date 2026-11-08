"""The shared agent runtime (CLAUDE.md §2.3): one executor, per-course SubjectPack config.

A Calc BC agent and an APUSH agent differ only in their pack (prompt, skills, rubrics,
content, tools). The ability registry picks the handler from the Run kind and question
shape. The executor checks that the ability is pinned on the Session and that the content
and ability versions it was pinned to are still the ones loaded, and never grades with
different content than the session started with.

An ability that needs no model still runs with none configured (`HSOS_LLM_PROVIDER=mock`);
everything else goes to the labeled synthetic fallback, which never produces an assessment.
"""

from __future__ import annotations

from app.domain.ability_registry import AbilityRegistry
from app.domain.ports.content import QuestionContent, SubjectPackRegistry
from app.domain.ports.execution import (
    ExecutionFailure,
    ExecutionOutput,
    ExecutionRequest,
    RunExecutor,
)
from app.domain.ports.llm import LlmGateway
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.ports.tools import ToolRunner
from app.domain.skills.ability import AbilityContext, question_shape
from app.domain.skills.catalog import PLATFORM_ABILITY_REGISTRY
from app.domain.types.run import RunKind


class SkillExecutor:
    def __init__(
        self,
        gateway: LlmGateway | None,
        registry: SubjectPackRegistry,
        tools: ToolRunner,
        clock: Clock,
        ids: IdFactory,
        *,
        fallback: RunExecutor | None = None,
        abilities: AbilityRegistry = PLATFORM_ABILITY_REGISTRY,
    ) -> None:
        if gateway is None and fallback is None:
            raise ValueError("without a model gateway a fallback executor is required")
        self._gateway = gateway
        self._registry = registry
        self._tools = tools
        self._clock = clock
        self._ids = ids
        self._fallback = fallback
        self._abilities = abilities

    def _runs_without_model(self, request: ExecutionRequest) -> bool:
        session = request.session
        question = (
            self._registry.question(
                session.course_id, session.activity.question_id, session.context_version.pack
            )
            if session.activity is not None
            else None
        )
        ability = self._abilities.for_run(request.run.kind, question_shape(question))
        return ability is not None and not ability.needs_model

    async def execute(self, request: ExecutionRequest) -> ExecutionOutput:
        if self._gateway is None and not self._runs_without_model(request):
            assert self._fallback is not None
            return await self._fallback.execute(request)
        session = request.session
        # The package version the Session pinned, even if a newer one is active now.
        pinned = session.context_version.pack
        pack = self._registry.pack(session.course_id, pinned)
        if pack is None:
            raise ExecutionFailure("COURSE_CONTENT_UNAVAILABLE")
        if pack.pack_version != pinned or pack.workflow_version != session.context_version.workflow:
            # Pinned content no longer matches: do not silently switch.
            raise ExecutionFailure("CONTENT_VERSION_CHANGED")
        question: QuestionContent | None = None
        if session.activity is not None:
            question = self._registry.question(
                session.course_id, session.activity.question_id, pinned
            )
            if question is None or question.version != session.activity.question_version:
                raise ExecutionFailure("CONTENT_VERSION_CHANGED")

        if request.run.kind is RunKind.ASSESS_SUBMISSION:
            submission = request.submission
            if submission is None:
                raise ExecutionFailure("SUBMISSION_NOT_FOUND")
            if question is None or question.question_id != submission.question_id:
                question = self._registry.question(
                    session.course_id, submission.question_id, pinned
                )
            if question is None or question.version != submission.question_version:
                raise ExecutionFailure("CONTENT_VERSION_CHANGED")

        ability = self._abilities.for_run(request.run.kind, question_shape(question))
        if ability is None:
            raise ExecutionFailure("UNSUPPORTED_RUN_KIND")
        if ability.ability_id not in session.agent_skills:
            raise ExecutionFailure("SKILL_NOT_ENABLED")
        # Sessions opened before abilities were versioned have nothing pinned to compare.
        pinned_ability = session.ability_versions.get(ability.ability_id)
        if pinned_ability is not None and pinned_ability != ability.version:
            raise ExecutionFailure("CONTENT_VERSION_CHANGED")
        return await ability.handler(
            AbilityContext(
                packs=self._registry,
                tools=self._tools,
                clock=self._clock,
                ids=self._ids,
                gateway=self._gateway,
                pack=pack,
                request=request,
                question=question,
            )
        )
