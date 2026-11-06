"""Admissions workspace commands and reads (Step 35, API.md §6.5).

Every operation requires the platform-managed `entitlements.admissions` grant
(ADMISSIONS_ACCESS_REQUIRED otherwise). Commands are idempotent; edits use If-Match.
Model work (fact proposals, outlines, feedback) is never done here: a command stores the
student's input and enqueues a Run in the same transaction (CLAUDE.md §2.4).

Rules:
- 35.1 A fact proposed from an interview answer is used only after the student confirms
  it (optionally rewording it). Facts the student types are confirmed on entry.
- 35.2 Deadlines carry a source URL and the date the student last checked it; the
  response labels each one verified / stale / unverified / unsourced.
- 35.3 Essay drafts are written only by the student. Outline and feedback come back as
  short items; nothing here writes or rewrites essay text.
- 35.4 Saving an activity requires the student to confirm it, and every fact it cites to
  be confirmed (FACTS_NOT_CONFIRMED otherwise).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from app.domain.commands import CommandKey, Outcome, find_replay, remember
from app.domain.errors import DomainError, ErrorCode
from app.domain.local_time import local_date
from app.domain.ports.repositories import Tx, UnitOfWork
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.runs import enqueue_run
from app.domain.types.actor import ActorContext, Permission
from app.domain.types.admissions import (
    FACT_CATEGORIES,
    Activity,
    Deadline,
    Essay,
    Fact,
    FactSource,
    FactStatus,
    FeedbackKind,
    FeedbackRequest,
    InterviewAnswer,
    InterviewPrompt,
)
from app.domain.types.run import Run, RunKind, RunStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class PromptSet:
    version: str
    prompts: Sequence[InterviewPrompt]

    @property
    def by_id(self) -> Mapping[str, InterviewPrompt]:
        return {p.prompt_id: p for p in self.prompts}


@dataclass(frozen=True, slots=True, kw_only=True)
class ActivityInput:
    name: str
    role: str
    description: str
    hours_per_week: int
    weeks_per_year: int
    fact_ids: Sequence[str]
    student_confirmed: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class DeadlineInput:
    school: str
    kind: str
    due_date: date
    source_url: str | None
    source_checked_on: date | None
    notes: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Queued[T]:
    value: T
    run: Run


def _not_found(what: str = "Not found.") -> DomainError:
    return DomainError(ErrorCode.NOT_FOUND, what)


def _version(current: int, expected: int) -> None:
    if current != expected:
        raise DomainError(ErrorCode.VERSION_CONFLICT, "This item changed; reload and retry.")


class AdmissionsService:
    def __init__(self, uow: UnitOfWork, prompts: PromptSet, clock: Clock, ids: IdFactory) -> None:
        self._uow = uow
        self._prompts = prompts
        self._clock = clock
        self._ids = ids

    async def _gate(self, tx: Tx, actor: ActorContext, write: bool = False) -> None:
        actor.require(Permission.TWIN_WRITE if write else Permission.TWIN_READ)
        if not (await tx.students.get_entitlements(actor)).admissions:
            raise DomainError(
                ErrorCode.ADMISSIONS_ACCESS_REQUIRED, "Admissions access has not been granted."
            )

    async def today(self, actor: ActorContext) -> date:
        async def body(tx: Tx) -> date:
            student = await tx.students.get(actor)
            tz = student.preferences.timezone if student else "UTC"
            return local_date(self._clock.now(), tz)

        return await self._uow.transaction(body)

    async def _read[T](self, actor: ActorContext, fn: Callable[[Tx], Awaitable[T]]) -> T:
        async def body(tx: Tx) -> T:
            await self._gate(tx, actor)
            return await fn(tx)

        return await self._uow.transaction(body)

    def _new_run(self, actor: ActorContext, kind: RunKind, subject_id: str) -> Run:
        now = self._clock.now()
        return Run(
            run_id=self._ids.new("run"), student_id=actor.student_id, session_id=None,
            status=RunStatus.QUEUED, kind=kind, subject_id=subject_id,
            created_at=now, updated_at=now,
        )  # fmt: skip

    async def _replayed_run(self, tx: Tx, actor: ActorContext, run_id: str) -> Run:
        run = await tx.runs.get(actor, run_id)
        if run is None:  # pragma: no cover - runs are never deleted
            raise _not_found()
        return run

    # ---- 35.1 Interview → proposed facts → confirmation -----------------------------------

    def prompts(self) -> PromptSet:
        return self._prompts

    async def answer(
        self, actor: ActorContext, prompt_id: str, text: str, cmd: CommandKey
    ) -> Outcome[Queued[InterviewAnswer]]:
        if prompt_id not in self._prompts.by_id:
            raise DomainError(ErrorCode.VALIDATION_FAILED, "Unknown interview prompt.")

        async def body(tx: Tx) -> Outcome[Queued[InterviewAnswer]]:
            await self._gate(tx, actor, write=True)
            now = self._clock.now()
            record = await find_replay(tx, actor, cmd)
            if record is not None:
                answer = await tx.admissions.get_answer(actor, record.resource_id)
                assert answer is not None
                run = await self._replayed_run(tx, actor, answer.run_id)
                return Outcome(value=Queued(value=answer, run=run), replayed=True)
            answer_id = self._ids.new("ans")
            run = self._new_run(actor, RunKind.ADMISSIONS_FACTS, answer_id)
            answer = InterviewAnswer(
                answer_id=answer_id, student_id=actor.student_id, prompt_id=prompt_id,
                prompt_set_version=self._prompts.version, text=text, run_id=run.run_id,
                created_at=now,
            )  # fmt: skip
            tx.admissions.save_answer(actor, answer)
            entry = await enqueue_run(
                tx, actor, run, now=now, ids=self._ids, causation_id=answer_id
            )
            remember(tx, actor, cmd, resource_type="admissions_answer", resource_id=answer_id,
                     response_status=202, now=now)  # fmt: skip
            return Outcome(value=Queued(value=answer, run=run), delivery_id=entry.delivery_id)

        return await self._uow.transaction(body)

    async def list_answers(self, actor: ActorContext) -> Sequence[InterviewAnswer]:
        return await self._read(actor, lambda tx: tx.admissions.list_answers(actor))

    async def list_facts(self, actor: ActorContext) -> Sequence[Fact]:
        return await self._read(actor, lambda tx: tx.admissions.list_facts(actor))

    async def add_fact(
        self, actor: ActorContext, text: str, category: str, cmd: CommandKey
    ) -> Outcome[Fact]:
        """A fact the student types is theirs: confirmed on entry."""
        if category not in FACT_CATEGORIES:
            raise DomainError(ErrorCode.VALIDATION_FAILED, "Unknown fact category.")

        async def body(tx: Tx) -> Outcome[Fact]:
            await self._gate(tx, actor, write=True)
            now = self._clock.now()
            record = await find_replay(tx, actor, cmd)
            if record is not None:
                fact = await tx.admissions.get_fact(actor, record.resource_id)
                assert fact is not None
                return Outcome(value=fact, replayed=True)
            fact = Fact(
                fact_id=self._ids.new("fact"), student_id=actor.student_id, text=text,
                category=category, status=FactStatus.CONFIRMED, source=FactSource.STUDENT,
                created_at=now, decided_at=now,
            )  # fmt: skip
            tx.admissions.save_fact(actor, fact)
            remember(tx, actor, cmd, resource_type="admissions_fact", resource_id=fact.fact_id,
                     response_status=201, now=now)  # fmt: skip
            return Outcome(value=fact)

        return await self._uow.transaction(body)

    async def decide_fact(
        self,
        actor: ActorContext,
        fact_id: str,
        confirm: bool,
        cmd: CommandKey,
        *,
        text: str | None = None,
    ) -> Outcome[Fact]:
        """Confirm (optionally in the student's own words) or reject a proposed fact."""

        async def body(tx: Tx) -> Outcome[Fact]:
            await self._gate(tx, actor, write=True)
            now = self._clock.now()
            record = await find_replay(tx, actor, cmd)
            fact = await tx.admissions.get_fact(actor, fact_id)
            if fact is None:
                raise _not_found("Fact not found.")
            if record is not None:
                return Outcome(value=fact, replayed=True, created=False)
            if fact.status is not FactStatus.PROPOSED:
                raise DomainError(
                    ErrorCode.INVALID_STATE_TRANSITION, f"This fact is already {fact.status.value}."
                )
            decided = dataclasses.replace(
                fact,
                status=FactStatus.CONFIRMED if confirm else FactStatus.REJECTED,
                text=text if (confirm and text) else fact.text,
                decided_at=now,
                version=fact.version + 1,
            )
            tx.admissions.save_fact(actor, decided)
            remember(tx, actor, cmd, resource_type="admissions_fact", resource_id=fact_id,
                     response_status=200, now=now)  # fmt: skip
            return Outcome(value=decided, created=False)

        return await self._uow.transaction(body)

    # ---- 35.4 Activities rest on confirmed facts ---------------------------------------------

    async def _check_facts(self, tx: Tx, actor: ActorContext, inp: ActivityInput) -> None:
        if not inp.student_confirmed:
            raise DomainError(
                ErrorCode.FACTS_NOT_CONFIRMED,
                "Confirm that this activity is accurate before saving it.",
            )
        for fid in inp.fact_ids:
            fact = await tx.admissions.get_fact(actor, fid)
            if fact is None or fact.status is not FactStatus.CONFIRMED:
                raise DomainError(
                    ErrorCode.FACTS_NOT_CONFIRMED,
                    "Every fact an activity cites must be confirmed first.",
                )

    async def list_activities(self, actor: ActorContext) -> Sequence[Activity]:
        return await self._read(actor, lambda tx: tx.admissions.list_activities(actor))

    async def create_activity(
        self, actor: ActorContext, inp: ActivityInput, cmd: CommandKey
    ) -> Outcome[Activity]:
        async def body(tx: Tx) -> Outcome[Activity]:
            await self._gate(tx, actor, write=True)
            now = self._clock.now()
            record = await find_replay(tx, actor, cmd)
            if record is not None:
                existing = await tx.admissions.get_activity(actor, record.resource_id)
                assert existing is not None
                return Outcome(value=existing, replayed=True)
            await self._check_facts(tx, actor, inp)
            activity = Activity(
                activity_id=self._ids.new("act"), student_id=actor.student_id, name=inp.name,
                role=inp.role, description=inp.description, hours_per_week=inp.hours_per_week,
                weeks_per_year=inp.weeks_per_year, fact_ids=tuple(inp.fact_ids),
                confirmed_at=now, created_at=now, updated_at=now,
            )  # fmt: skip
            tx.admissions.save_activity(actor, activity)
            remember(tx, actor, cmd, resource_type="admissions_activity",
                     resource_id=activity.activity_id, response_status=201, now=now)  # fmt: skip
            return Outcome(value=activity)

        return await self._uow.transaction(body)

    async def update_activity(
        self, actor: ActorContext, activity_id: str, inp: ActivityInput, expected_version: int
    ) -> Activity:
        async def body(tx: Tx) -> Activity:
            await self._gate(tx, actor, write=True)
            now = self._clock.now()
            current = await tx.admissions.get_activity(actor, activity_id)
            if current is None:
                raise _not_found("Activity not found.")
            _version(current.version, expected_version)
            await self._check_facts(tx, actor, inp)
            updated = dataclasses.replace(
                current, name=inp.name, role=inp.role, description=inp.description,
                hours_per_week=inp.hours_per_week, weeks_per_year=inp.weeks_per_year,
                fact_ids=tuple(inp.fact_ids), confirmed_at=now, updated_at=now,
                version=current.version + 1,
            )  # fmt: skip
            tx.admissions.save_activity(actor, updated)
            return updated

        return await self._uow.transaction(body)

    # ---- 35.2 Sourced deadlines ------------------------------------------------------------

    async def list_deadlines(self, actor: ActorContext) -> Sequence[Deadline]:
        return await self._read(actor, lambda tx: tx.admissions.list_deadlines(actor))

    async def create_deadline(
        self, actor: ActorContext, inp: DeadlineInput, cmd: CommandKey
    ) -> Outcome[Deadline]:
        async def body(tx: Tx) -> Outcome[Deadline]:
            await self._gate(tx, actor, write=True)
            now = self._clock.now()
            record = await find_replay(tx, actor, cmd)
            if record is not None:
                existing = await tx.admissions.get_deadline(actor, record.resource_id)
                assert existing is not None
                return Outcome(value=existing, replayed=True)
            deadline = Deadline(
                deadline_id=self._ids.new("dl"), student_id=actor.student_id, school=inp.school,
                kind=inp.kind, due_date=inp.due_date, source_url=inp.source_url,
                source_checked_on=inp.source_checked_on, notes=inp.notes,
                created_at=now, updated_at=now,
            )  # fmt: skip
            tx.admissions.save_deadline(actor, deadline)
            remember(tx, actor, cmd, resource_type="admissions_deadline",
                     resource_id=deadline.deadline_id, response_status=201, now=now)  # fmt: skip
            return Outcome(value=deadline)

        return await self._uow.transaction(body)

    async def update_deadline(
        self, actor: ActorContext, deadline_id: str, inp: DeadlineInput, expected_version: int
    ) -> Deadline:
        async def body(tx: Tx) -> Deadline:
            await self._gate(tx, actor, write=True)
            current = await tx.admissions.get_deadline(actor, deadline_id)
            if current is None:
                raise _not_found("Deadline not found.")
            _version(current.version, expected_version)
            updated = dataclasses.replace(
                current, school=inp.school, kind=inp.kind, due_date=inp.due_date,
                source_url=inp.source_url, source_checked_on=inp.source_checked_on,
                notes=inp.notes, updated_at=self._clock.now(), version=current.version + 1,
            )  # fmt: skip
            tx.admissions.save_deadline(actor, updated)
            return updated

        return await self._uow.transaction(body)

    # ---- 35.3 Essays: the student's text, coaching only ------------------------------------

    async def list_essays(self, actor: ActorContext) -> Sequence[Essay]:
        return await self._read(actor, lambda tx: tx.admissions.list_essays(actor))

    async def get_essay(self, actor: ActorContext, essay_id: str) -> Essay:
        async def read(tx: Tx) -> Essay:
            essay = await tx.admissions.get_essay(actor, essay_id)
            if essay is None:
                raise _not_found("Essay not found.")
            return essay

        return await self._read(actor, read)

    async def create_essay(
        self, actor: ActorContext, title: str, prompt: str, cmd: CommandKey
    ) -> Outcome[Essay]:
        async def body(tx: Tx) -> Outcome[Essay]:
            await self._gate(tx, actor, write=True)
            now = self._clock.now()
            record = await find_replay(tx, actor, cmd)
            if record is not None:
                existing = await tx.admissions.get_essay(actor, record.resource_id)
                assert existing is not None
                return Outcome(value=existing, replayed=True)
            essay = Essay(
                essay_id=self._ids.new("essay"), student_id=actor.student_id, title=title,
                prompt=prompt, draft="", created_at=now, updated_at=now,
            )  # fmt: skip
            tx.admissions.save_essay(actor, essay)
            remember(tx, actor, cmd, resource_type="admissions_essay",
                     resource_id=essay.essay_id, response_status=201, now=now)  # fmt: skip
            return Outcome(value=essay)

        return await self._uow.transaction(body)

    async def save_draft(
        self, actor: ActorContext, essay_id: str, draft: str, expected_version: int
    ) -> Essay:
        async def body(tx: Tx) -> Essay:
            await self._gate(tx, actor, write=True)
            essay = await tx.admissions.get_essay(actor, essay_id)
            if essay is None:
                raise _not_found("Essay not found.")
            _version(essay.version, expected_version)
            if essay.active_run_id is not None:
                raise DomainError(
                    ErrorCode.RUN_IN_PROGRESS, "Feedback is being prepared for this version."
                )
            saved = dataclasses.replace(
                essay, draft=draft, updated_at=self._clock.now(), version=essay.version + 1
            )
            tx.admissions.save_essay(actor, saved)
            return saved

        return await self._uow.transaction(body)

    async def request_feedback(
        self, actor: ActorContext, essay_id: str, kind: FeedbackKind, cmd: CommandKey
    ) -> Outcome[Queued[FeedbackRequest]]:
        async def body(tx: Tx) -> Outcome[Queued[FeedbackRequest]]:
            await self._gate(tx, actor, write=True)
            now = self._clock.now()
            record = await find_replay(tx, actor, cmd)
            if record is not None:
                fb = await tx.admissions.get_feedback(actor, record.resource_id)
                assert fb is not None
                run = await self._replayed_run(tx, actor, fb.run_id)
                return Outcome(value=Queued(value=fb, run=run), replayed=True)
            essay = await tx.admissions.get_essay(actor, essay_id)
            if essay is None:
                raise _not_found("Essay not found.")
            if essay.active_run_id is not None:
                raise DomainError(ErrorCode.RUN_IN_PROGRESS, "Feedback is already being prepared.")
            if kind is FeedbackKind.FEEDBACK and not essay.draft.strip():
                raise DomainError(
                    ErrorCode.VALIDATION_FAILED, "Write a draft first; feedback is on your text."
                )
            if kind is FeedbackKind.OUTLINE and not any(
                f.status is FactStatus.CONFIRMED for f in await tx.admissions.list_facts(actor)
            ):
                raise DomainError(
                    ErrorCode.FACTS_NOT_CONFIRMED,
                    "Confirm at least one fact about yourself before asking for an outline.",
                )
            feedback_id = self._ids.new("fb")
            run = self._new_run(actor, RunKind.ADMISSIONS_FEEDBACK, feedback_id)
            fb = FeedbackRequest(
                feedback_id=feedback_id, student_id=actor.student_id, essay_id=essay_id,
                essay_version=essay.version, kind=kind, run_id=run.run_id, created_at=now,
            )  # fmt: skip
            tx.admissions.save_feedback(actor, fb)
            tx.admissions.save_essay(
                actor, dataclasses.replace(essay, active_run_id=run.run_id, updated_at=now)
            )
            entry = await enqueue_run(
                tx, actor, run, now=now, ids=self._ids, causation_id=feedback_id
            )
            remember(tx, actor, cmd, resource_type="admissions_feedback",
                     resource_id=feedback_id, response_status=202, now=now)  # fmt: skip
            return Outcome(value=Queued(value=fb, run=run), delivery_id=entry.delivery_id)

        return await self._uow.transaction(body)

    async def list_feedback(self, actor: ActorContext, essay_id: str) -> Sequence[FeedbackRequest]:
        async def read(tx: Tx) -> Sequence[FeedbackRequest]:
            if await tx.admissions.get_essay(actor, essay_id) is None:
                raise _not_found("Essay not found.")
            return [f for f in await tx.admissions.list_feedback(actor) if f.essay_id == essay_id]

        return await self._read(actor, read)
