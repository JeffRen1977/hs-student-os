"""AssessmentService: the only boundary through which grading becomes evidence (Step 18).

`commit_assessment` runs inside the worker's commit transaction, after the fencing token
check, and writes Assessment + mastery projection + session completion input + events in
the same transaction as the Run's terminal state. It validates the draft *semantically*
against stored records (submission, pinned question/rubric versions, evidence spans, tool
ledger) and derives skill evidence and hint usage itself, so neither the model nor the
client can assert them.

`complete_session` closes a Session/Task from saved accepted assessments only; it
summarizes and never re-applies mastery.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence
from datetime import datetime

from app.domain.commands import CommandKey, Outcome, find_replay, remember
from app.domain.errors import DomainError, ErrorCode
from app.domain.events import EventPublisher
from app.domain.mastery_service import apply_assessment
from app.domain.ports.content import QuestionContent, RubricContent, SubjectPackRegistry
from app.domain.ports.repositories import EventDraft, Tx, UnitOfWork
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.session_service import SESSION_RESOURCE, get_owned_session
from app.domain.types.actor import ActorContext, Permission
from app.domain.types.assessment import (
    Assessment,
    AssessmentStatus,
    EvidenceObservation,
    HintUsage,
    Provenance,
    RubricResult,
    SkillEvidence,
    Uncertainty,
    UncertaintyLevel,
)
from app.domain.types.assessment_draft import AssessmentDraft
from app.domain.types.common import PageRequest, PaginatedResponse
from app.domain.types.event import EventType
from app.domain.types.run import Run, RunKind
from app.domain.types.session import SESSION_TRANSITIONS, Session, SessionStatus, completion_for
from app.domain.types.submission import Submission
from app.domain.types.task import TASK_TRANSITIONS, TaskStatus
from app.domain.types.transitions import ensure_transition

_EVIDENCE_REF = re.compile(r"^(?P<sub>[A-Za-z0-9_\-]+):text:(?P<a>\d+)-(?P<b>\d+)$")
ALL_PAGES = PageRequest(limit=100)


class AssessmentRejectedError(Exception):
    """The draft failed semantic validation; nothing from this commit is written."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def assessment_id_for(run_id: str) -> str:
    """One assessment per run, deterministically: a replayed commit finds the first one."""
    return f"asm_{run_id}"


def derive_skill_evidence(
    question: QuestionContent,
    rubric: RubricContent,
    results: Sequence[RubricResult],
    *,
    assisted: bool,
) -> list[SkillEvidence]:
    """Per question skill, over its *assessable* criteria: all full → correct; none earned →
    incorrect; otherwise partially correct. A skill whose criteria could not be assessed
    (e.g. they only failed because of an earlier error) gets no evidence at all, so a
    downstream zero is never recorded as a weakness. Assisted work is never independent."""
    by_id = {r.criterion_id: r for r in results}
    evidence: list[SkillEvidence] = []
    for skill in question.skill_ids:
        mapped = [
            by_id[c.criterion_id]
            for c in rubric.criteria
            if skill in c.skill_ids and by_id[c.criterion_id].assessable
        ]
        if not mapped:
            continue
        if all(r.earned == r.possible for r in mapped):
            observation = (
                EvidenceObservation.CORRECT_WITH_HINT
                if assisted
                else EvidenceObservation.CORRECT_INDEPENDENT
            )
        elif all(r.earned == 0 for r in mapped):
            observation = EvidenceObservation.INCORRECT
        else:
            observation = EvidenceObservation.PARTIALLY_CORRECT
        evidence.append(SkillEvidence(skill_id=skill, observation=observation))
    return evidence


def validate_draft(
    draft: AssessmentDraft,
    run: Run,
    submission: Submission | None,
    session: Session | None,
    question: QuestionContent | None,
    rubric: RubricContent | None,
    known_tool_result_ids: set[str],
) -> tuple[Submission, Session, QuestionContent, RubricContent]:
    if run.kind is not RunKind.ASSESS_SUBMISSION or run.submission_id != draft.submission_id:
        raise AssessmentRejectedError("run_submission_mismatch")
    if submission is None or session is None or submission.session_id != session.session_id:
        raise AssessmentRejectedError("submission_not_in_session")
    if run.session_id != session.session_id:
        raise AssessmentRejectedError("run_not_in_session")
    if question is None or rubric is None:
        raise AssessmentRejectedError("content_not_found")
    if not (
        draft.question_id == submission.question_id == question.question_id
        and draft.question_version == submission.question_version == question.version
    ):
        raise AssessmentRejectedError("question_version_mismatch")
    if (draft.rubric_id, draft.rubric_version) != (question.rubric_id, question.rubric_version) or (
        (rubric.rubric_id, rubric.version) != (question.rubric_id, question.rubric_version)
    ):
        raise AssessmentRejectedError("rubric_version_mismatch")
    act = session.activity
    if act is not None and (
        (act.question_id, act.question_version) != (question.question_id, question.version)
        or (act.rubric_id, act.rubric_version) != (rubric.rubric_id, rubric.version)
    ):
        raise AssessmentRejectedError("not_the_session_activity")
    if draft.workflow_version != session.context_version.workflow:
        raise AssessmentRejectedError("workflow_version_mismatch")

    limits = {c.criterion_id: c.max_points for c in rubric.criteria}
    if [r.criterion_id for r in draft.rubric_results] != [c.criterion_id for c in rubric.criteria]:
        raise AssessmentRejectedError("rubric_criteria_mismatch")
    length = len(submission.answer.text)
    for r in draft.rubric_results:
        if r.possible != limits[r.criterion_id] or not 0 <= r.earned <= r.possible:
            raise AssessmentRejectedError("rubric_points_invalid")
        if r.earned > 0 and not r.evidence_refs:
            raise AssessmentRejectedError("points_without_evidence")
        if r.earned > 0 and not r.assessable:
            raise AssessmentRejectedError("points_on_unassessable_criterion")
        for ref in r.evidence_refs:
            m = _EVIDENCE_REF.fullmatch(ref)
            if m is None or m["sub"] != submission.submission_id:
                raise AssessmentRejectedError("evidence_ref_invalid")
            if not 0 <= int(m["a"]) < int(m["b"]) <= length:
                raise AssessmentRejectedError("evidence_ref_out_of_range")
    if not set(draft.tool_result_ids) <= known_tool_result_ids:
        raise AssessmentRejectedError("unknown_tool_result")
    return submission, session, question, rubric


class AssessmentService:
    def __init__(
        self,
        uow: UnitOfWork,
        registry: SubjectPackRegistry,
        clock: Clock,
        ids: IdFactory,
        publisher: EventPublisher,
    ) -> None:
        self._uow = uow
        self._registry = registry
        self._clock = clock
        self._ids = ids
        self._publisher = publisher

    # ---- Commit (worker, inside the run's commit transaction) -------------------------

    async def commit_assessment(
        self,
        tx: Tx,
        actor: ActorContext,
        run: Run,
        draft: AssessmentDraft,
        *,
        tool_result_ids: set[str],
        now: datetime,
    ) -> Assessment:
        actor.require(Permission.RUN_EXECUTE)
        existing = await tx.assessments.get(actor, assessment_id_for(run.run_id))
        if existing is not None:
            return existing  # replayed commit: the evidence was already applied once

        submission = await tx.submissions.get(actor, draft.submission_id)
        session = await tx.sessions.get(actor, run.session_id) if run.session_id else None
        course_id = session.course_id if session else ""
        question = self._registry.question(course_id, draft.question_id)
        rubric = self._registry.rubric(course_id, draft.rubric_id, draft.rubric_version)
        submission, session, question, rubric = validate_draft(
            draft, run, submission, session, question, rubric, tool_result_ids
        )

        superseded: Assessment | None = None
        if draft.supersedes_assessment_id is not None:
            superseded = await tx.assessments.get(actor, draft.supersedes_assessment_id)
            if superseded is None or superseded.submission_id != submission.submission_id:
                raise AssessmentRejectedError("superseded_assessment_invalid")
            # Regrades form a chain: replacing an assessment that was already replaced
            # would let two regrades both count, stacking evidence for one submission.
            if any(
                a.supersedes_assessment_id == superseded.assessment_id
                for a in await self._session_assessments(tx, actor, session.session_id)
            ):
                raise AssessmentRejectedError("superseded_assessment_already_replaced")

        status = draft.status
        evidence = (
            derive_skill_evidence(
                question, rubric, draft.rubric_results, assisted=submission.is_assisted
            )
            if status is AssessmentStatus.ACCEPTED
            else []
        )
        level, reasons = draft.uncertainty.level, list(draft.uncertainty.reasons)
        if submission.is_assisted and level is UncertaintyLevel.LOW:
            level = UncertaintyLevel.LIMITED
        if submission.server_hint_count and "hint_assisted" not in reasons:
            reasons.append("hint_assisted")
        assessment = Assessment(
            assessment_id=assessment_id_for(run.run_id),
            student_id=actor.student_id,
            submission_id=submission.submission_id,
            session_id=session.session_id,
            run_id=run.run_id,
            status=status,
            question_id=question.question_id,
            question_version=question.version,
            rubric_id=rubric.rubric_id,
            rubric_version=rubric.version,
            rubric_results=tuple(draft.rubric_results),
            hint_usage=HintUsage(server_hint_count=submission.server_hint_count),
            skill_evidence=tuple(evidence),
            uncertainty=Uncertainty(level=level, reasons=tuple(r[:64] for r in reasons)),
            provenance=Provenance(
                model_version=draft.model_version,
                workflow_version=draft.workflow_version,
                tool_result_ids=tuple(draft.tool_result_ids),
            ),
            supersedes_assessment_id=draft.supersedes_assessment_id,
            feedback=draft.feedback,
            created_at=now,
        )
        tx.assessments.create(actor, assessment)
        changed = await apply_assessment(tx, actor, assessment, superseded=superseded, now=now)

        has_accepted = session.has_accepted_assessment or assessment.updates_mastery
        if superseded is not None and superseded.updates_mastery and not assessment.updates_mastery:
            has_accepted = await self._session_has_accepted(
                tx, actor, session.session_id, assessment
            )
        if has_accepted != session.has_accepted_assessment:
            tx.sessions.save(
                actor,
                dataclasses.replace(
                    session,
                    has_accepted_assessment=has_accepted,
                    completion=completion_for(session.status, session.active_run_id, has_accepted),
                    version=session.version + 1,
                    updated_at=now,
                ),
            )

        await self._event(
            tx, actor, EventType.ASSESSMENT_COMPLETED, run, now,
            {"assessmentId": assessment.assessment_id, "status": status.value},
        )  # fmt: skip
        if changed:
            await self._event(
                tx, actor, EventType.MASTERY_UPDATED, run, now,
                {"skillIds": changed, "assessmentId": assessment.assessment_id},
            )  # fmt: skip
        return assessment

    async def _session_has_accepted(
        self, tx: Tx, actor: ActorContext, session_id: str, latest: Assessment
    ) -> bool:
        items = [latest, *await self._session_assessments(tx, actor, session_id)]
        superseded = {a.supersedes_assessment_id for a in items if a.supersedes_assessment_id}
        return any(a.updates_mastery and a.assessment_id not in superseded for a in items)

    @staticmethod
    async def _session_assessments(
        tx: Tx, actor: ActorContext, session_id: str
    ) -> list[Assessment]:
        """Stored assessments of the session (queries do not see this transaction's writes)."""
        items: list[Assessment] = []
        page = ALL_PAGES
        while True:
            batch = await tx.assessments.list_for_session(actor, session_id, page)
            items.extend(batch.items)
            if batch.next_cursor is None:
                return items
            page = PageRequest(cursor=batch.next_cursor, limit=100)

    async def _event(
        self,
        tx: Tx,
        actor: ActorContext,
        kind: EventType,
        run: Run,
        now: datetime,
        payload: dict[str, object],
    ) -> None:
        # A subscribed event also writes a consumer wake (outbox, same transaction).
        await self._publisher.publish(
            tx,
            actor,
            EventDraft(
                type=kind,
                causation_id=run.submission_id or run.run_id,
                session_id=run.session_id,
                run_id=run.run_id,
                payload=payload,
            ),
            event_id=self._ids.new("evt"),
            now=now,
        )

    # ---- Complete (student command) ---------------------------------------------------

    async def complete_session(
        self, actor: ActorContext, session_id: str, cmd: CommandKey
    ) -> Outcome[Session]:
        """OPEN → COMPLETED (and its Task → COMPLETED) when the server's rule is met: no
        active Run and at least one accepted, non-superseded assessment. Mastery was
        applied when each assessment was committed and is not touched again here."""
        actor.require(Permission.LEARNING_COMMAND)

        async def write(tx: Tx) -> Outcome[Session]:
            replay = await find_replay(tx, actor, cmd)
            if replay is not None:
                session = await get_owned_session(tx, actor, replay.resource_id)
                return Outcome(value=session, replayed=True, created=False)

            session = await get_owned_session(tx, actor, session_id)
            now = self._clock.now()
            if session.status is SessionStatus.COMPLETED:
                remember(
                    tx, actor, cmd, resource_type=SESSION_RESOURCE,
                    resource_id=session_id, response_status=200, now=now,
                )  # fmt: skip
                return Outcome(value=session, created=False)
            ensure_transition(
                SESSION_TRANSITIONS, session.status, SessionStatus.COMPLETED, entity="Session"
            )
            if session.active_run_id is not None:
                run = await tx.runs.get(actor, session.active_run_id)
                if run is not None and not run.is_terminal:
                    raise DomainError(ErrorCode.RUN_IN_PROGRESS, "A run is still active.")
            if not session.has_accepted_assessment:
                raise DomainError(
                    ErrorCode.COMPLETION_REQUIREMENTS_NOT_MET,
                    "An accepted assessment is required before completing this session.",
                )
            completed = dataclasses.replace(
                session,
                status=SessionStatus.COMPLETED,
                active_run_id=None,
                completion=completion_for(SessionStatus.COMPLETED, None, True),
                version=session.version + 1,
                updated_at=now,
            )
            tx.sessions.save(actor, completed)
            task = await tx.tasks.get(actor, session.task_id)
            if task is not None and task.status is TaskStatus.IN_PROGRESS:
                ensure_transition(
                    TASK_TRANSITIONS, task.status, TaskStatus.COMPLETED, entity="Task"
                )
                tx.tasks.save(
                    actor,
                    dataclasses.replace(
                        task,
                        status=TaskStatus.COMPLETED,
                        open_session_id=None,
                        version=task.version + 1,
                    ),
                    now=now,
                )
            await tx.events.append(
                actor,
                EventDraft(
                    type=EventType.SESSION_COMPLETED,
                    causation_id=session_id,
                    session_id=session_id,
                    payload={"taskId": session.task_id},
                ),
                event_id=self._ids.new("evt"),
                now=now,
            )
            remember(
                tx, actor, cmd, resource_type=SESSION_RESOURCE,
                resource_id=session_id, response_status=200, now=now,
            )  # fmt: skip
            return Outcome(value=completed)

        return await self._uow.transaction(write)

    # ---- Reads ------------------------------------------------------------------------

    async def get_assessment(self, actor: ActorContext, assessment_id: str) -> Assessment:
        actor.require(Permission.LEARNING_READ)

        async def read(tx: Tx) -> Assessment:
            assessment = await tx.assessments.get(actor, assessment_id)
            if assessment is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Assessment not found.")
            return assessment

        return await self._uow.transaction(read)

    async def list_for_session(
        self, actor: ActorContext, session_id: str, page: PageRequest
    ) -> PaginatedResponse[Assessment]:
        actor.require(Permission.LEARNING_READ)

        async def read(tx: Tx) -> PaginatedResponse[Assessment]:
            await get_owned_session(tx, actor, session_id)
            return await tx.assessments.list_for_session(actor, session_id, page)

        return await self._uow.transaction(read)
