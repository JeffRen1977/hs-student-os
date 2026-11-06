"""Worker side of admissions runs (Step 35), driven by RunExecutionService.

Same three phases as every run (BACKEND.md §5.3):
1. `load` inside the lease transaction: re-check admissions access and read the inputs;
2. `execute` outside any transaction: the model call (`app.domain.skills.admissions`);
3. `commit` inside the fenced commit transaction: proposed facts or feedback items, written
   together with the Run's terminal state, or not at all.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.domain.errors import ErrorCode
from app.domain.ports.execution import ExecutionFailure
from app.domain.ports.llm import LlmGateway
from app.domain.ports.repositories import Tx
from app.domain.ports.runtime import IdFactory
from app.domain.skills import admissions as skill
from app.domain.types.actor import ActorContext
from app.domain.types.admissions import (
    Essay,
    Fact,
    FactSource,
    FactStatus,
    FeedbackItem,
    FeedbackRequest,
    InterviewAnswer,
    InterviewPrompt,
)
from app.domain.types.run import Run, RunKind


@dataclass(frozen=True, slots=True, kw_only=True)
class AdmissionsJob:
    run: Run
    prompt: InterviewPrompt | None = None
    answer: InterviewAnswer | None = None
    essay: Essay | None = None
    feedback: FeedbackRequest | None = None
    confirmed: Sequence[Fact] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class AdmissionsOutput:
    model_version: str
    usage_tokens: int
    facts: Sequence[skill.ProposedFact] = ()
    items: Sequence[FeedbackItem] = ()


class AdmissionsRunner:
    def __init__(
        self,
        gateway: LlmGateway | None,
        prompts: Mapping[str, InterviewPrompt],
        ids: IdFactory,
    ) -> None:
        self._gateway = gateway
        self._prompts = dict(prompts)
        self._ids = ids

    async def load(self, tx: Tx, actor: ActorContext, run: Run) -> AdmissionsJob | str:
        """The job, or an error code to fail the run with."""
        if not (await tx.students.get_entitlements(actor)).admissions:
            return ErrorCode.ADMISSIONS_ACCESS_REQUIRED.value
        assert run.subject_id is not None
        if run.kind is RunKind.ADMISSIONS_FACTS:
            answer = await tx.admissions.get_answer(actor, run.subject_id)
            prompt = self._prompts.get(answer.prompt_id) if answer else None
            if answer is None or prompt is None:
                return "ADMISSIONS_INPUT_NOT_FOUND"
            return AdmissionsJob(run=run, prompt=prompt, answer=answer)
        feedback = await tx.admissions.get_feedback(actor, run.subject_id)
        essay = await tx.admissions.get_essay(actor, feedback.essay_id) if feedback else None
        if feedback is None or essay is None:
            return "ADMISSIONS_INPUT_NOT_FOUND"
        if essay.version != feedback.essay_version:
            return "ESSAY_CHANGED"  # edits are blocked while a run is active; defensive
        confirmed = [
            f for f in await tx.admissions.list_facts(actor) if f.status is FactStatus.CONFIRMED
        ]
        return AdmissionsJob(run=run, essay=essay, feedback=feedback, confirmed=confirmed)

    async def execute(self, job: AdmissionsJob) -> AdmissionsOutput:
        if self._gateway is None:
            raise ExecutionFailure("MODEL_UNAVAILABLE")  # no synthetic admissions output
        if job.run.kind is RunKind.ADMISSIONS_FACTS:
            assert job.prompt is not None and job.answer is not None
            facts = await skill.propose_facts(self._gateway, job.prompt, job.answer, job.run.run_id)
            return AdmissionsOutput(
                model_version=facts.model_version, usage_tokens=facts.usage_tokens,
                facts=facts.value,
            )  # fmt: skip
        assert job.essay is not None and job.feedback is not None
        out = await skill.essay_feedback(
            self._gateway, job.essay, job.feedback.kind, job.confirmed, job.run.run_id
        )
        return AdmissionsOutput(
            model_version=out.model_version, usage_tokens=out.usage_tokens, items=out.value
        )

    async def commit(
        self, tx: Tx, actor: ActorContext, run: Run, output: AdmissionsOutput, now: datetime
    ) -> None:
        assert run.subject_id is not None
        if run.kind is RunKind.ADMISSIONS_FACTS:
            for p in output.facts:
                tx.admissions.save_fact(
                    actor,
                    Fact(
                        fact_id=self._ids.new("fact"),
                        student_id=actor.student_id,
                        text=p.text,
                        category=p.category,
                        status=FactStatus.PROPOSED,
                        source=FactSource.INTERVIEW,
                        created_at=now,
                        answer_id=run.subject_id,
                        quote=p.quote,
                    ),
                )
            return
        feedback = await tx.admissions.get_feedback(actor, run.subject_id)
        if feedback is not None:
            tx.admissions.save_feedback(
                actor,
                dataclasses.replace(
                    feedback,
                    items=tuple(output.items),
                    model_version=output.model_version,
                    completed_at=now,
                ),
            )
