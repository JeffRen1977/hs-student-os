"""Admissions workspace documents (Step 35, BACKEND.md §3). All under the student:

    students/{id}/admissionsAnswers/{answerId}      interview answers (student text)
    students/{id}/admissionsFacts/{factId}          proposed / confirmed / rejected facts
    students/{id}/admissionsActivities/{id}         activity entries resting on facts
    students/{id}/admissionsDeadlines/{id}          deadlines with source + check date
    students/{id}/admissionsEssays/{essayId}        the student's own drafts
    students/{id}/admissionsFeedback/{feedbackId}   outline/feedback per essay version

Lists are small and read whole (ordered by a single field, so no composite index).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from app.adapters.firestore import paths
from app.adapters.firestore.documents import Doc, DocTxn, QuerySpec
from app.domain.types.actor import ActorContext
from app.domain.types.admissions import (
    Activity,
    Deadline,
    Essay,
    Fact,
    FactSource,
    FactStatus,
    FeedbackItem,
    FeedbackItemType,
    FeedbackKind,
    FeedbackRequest,
    InterviewAnswer,
)

LIST_LIMIT = 200


def _check(actor: ActorContext, student_id: str) -> None:
    if student_id != actor.student_id:
        raise ValueError("document does not belong to actor")


def _day(value: object) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) else None


class FirestoreAdmissionsStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def _get(self, actor: ActorContext, coll: str, doc_id: str) -> Doc | None:
        return await self._txn.get(paths.sub(actor, coll, doc_id))

    async def _list(self, actor: ActorContext, coll: str, order: str) -> list[Doc]:
        return await self._txn.query(
            paths.sub(actor, coll), QuerySpec(order_by=(order,), limit=LIST_LIMIT)
        )

    # ---- Interview answers -------------------------------------------------------------

    @staticmethod
    def _answer(d: Doc) -> InterviewAnswer:
        return InterviewAnswer(
            answer_id=d["answerId"], student_id=d["studentId"], prompt_id=d["promptId"],
            prompt_set_version=d["promptSetVersion"], text=d["text"], run_id=d["runId"],
            created_at=d["createdAt"],
        )  # fmt: skip

    async def get_answer(self, actor: ActorContext, answer_id: str) -> InterviewAnswer | None:
        d = await self._get(actor, "admissionsAnswers", answer_id)
        return self._answer(d) if d else None

    async def list_answers(self, actor: ActorContext) -> Sequence[InterviewAnswer]:
        return [self._answer(d) for d in await self._list(actor, "admissionsAnswers", "createdAt")]

    def save_answer(self, actor: ActorContext, a: InterviewAnswer) -> None:
        _check(actor, a.student_id)
        self._txn.set(
            paths.sub(actor, "admissionsAnswers", a.answer_id),
            {"answerId": a.answer_id, "studentId": a.student_id, "promptId": a.prompt_id,
             "promptSetVersion": a.prompt_set_version, "text": a.text, "runId": a.run_id,
             "createdAt": a.created_at},
        )  # fmt: skip

    # ---- Facts -------------------------------------------------------------------------

    @staticmethod
    def _fact(d: Doc) -> Fact:
        return Fact(
            fact_id=d["factId"], student_id=d["studentId"], text=d["text"],
            category=d["category"], status=FactStatus(d["status"]),
            source=FactSource(d["source"]), created_at=d["createdAt"],
            answer_id=d.get("answerId"), quote=d.get("quote"), decided_at=d.get("decidedAt"),
            version=int(d.get("version", 1)),
        )  # fmt: skip

    async def get_fact(self, actor: ActorContext, fact_id: str) -> Fact | None:
        d = await self._get(actor, "admissionsFacts", fact_id)
        return self._fact(d) if d else None

    async def list_facts(self, actor: ActorContext) -> Sequence[Fact]:
        return [self._fact(d) for d in await self._list(actor, "admissionsFacts", "createdAt")]

    def save_fact(self, actor: ActorContext, f: Fact) -> None:
        _check(actor, f.student_id)
        self._txn.set(
            paths.sub(actor, "admissionsFacts", f.fact_id),
            {"factId": f.fact_id, "studentId": f.student_id, "text": f.text,
             "category": f.category, "status": f.status.value, "source": f.source.value,
             "createdAt": f.created_at, "answerId": f.answer_id, "quote": f.quote,
             "decidedAt": f.decided_at, "version": f.version},
        )  # fmt: skip

    # ---- Activities --------------------------------------------------------------------

    @staticmethod
    def _activity(d: Doc) -> Activity:
        return Activity(
            activity_id=d["activityId"], student_id=d["studentId"], name=d["name"],
            role=d["role"], description=d["description"],
            hours_per_week=int(d["hoursPerWeek"]), weeks_per_year=int(d["weeksPerYear"]),
            fact_ids=tuple(d.get("factIds", ())), confirmed_at=d["confirmedAt"],
            created_at=d["createdAt"], updated_at=d["updatedAt"],
            version=int(d.get("version", 1)),
        )  # fmt: skip

    async def get_activity(self, actor: ActorContext, activity_id: str) -> Activity | None:
        d = await self._get(actor, "admissionsActivities", activity_id)
        return self._activity(d) if d else None

    async def list_activities(self, actor: ActorContext) -> Sequence[Activity]:
        docs = await self._list(actor, "admissionsActivities", "createdAt")
        return [self._activity(d) for d in docs]

    def save_activity(self, actor: ActorContext, a: Activity) -> None:
        _check(actor, a.student_id)
        self._txn.set(
            paths.sub(actor, "admissionsActivities", a.activity_id),
            {"activityId": a.activity_id, "studentId": a.student_id, "name": a.name,
             "role": a.role, "description": a.description, "hoursPerWeek": a.hours_per_week,
             "weeksPerYear": a.weeks_per_year, "factIds": list(a.fact_ids),
             "confirmedAt": a.confirmed_at, "createdAt": a.created_at,
             "updatedAt": a.updated_at, "version": a.version},
        )  # fmt: skip

    # ---- Deadlines ---------------------------------------------------------------------

    @staticmethod
    def _deadline(d: Doc) -> Deadline:
        due = _day(d["dueDate"])
        assert due is not None
        return Deadline(
            deadline_id=d["deadlineId"], student_id=d["studentId"], school=d["school"],
            kind=d["kind"], due_date=due, source_url=d.get("sourceUrl"),
            source_checked_on=_day(d.get("sourceCheckedOn")), notes=d.get("notes", ""),
            created_at=d["createdAt"], updated_at=d["updatedAt"],
            version=int(d.get("version", 1)),
        )  # fmt: skip

    async def get_deadline(self, actor: ActorContext, deadline_id: str) -> Deadline | None:
        d = await self._get(actor, "admissionsDeadlines", deadline_id)
        return self._deadline(d) if d else None

    async def list_deadlines(self, actor: ActorContext) -> Sequence[Deadline]:
        docs = await self._list(actor, "admissionsDeadlines", "dueDate")
        return [self._deadline(d) for d in docs]

    def save_deadline(self, actor: ActorContext, x: Deadline) -> None:
        _check(actor, x.student_id)
        self._txn.set(
            paths.sub(actor, "admissionsDeadlines", x.deadline_id),
            {"deadlineId": x.deadline_id, "studentId": x.student_id, "school": x.school,
             "kind": x.kind, "dueDate": x.due_date.isoformat(), "sourceUrl": x.source_url,
             "sourceCheckedOn": x.source_checked_on.isoformat() if x.source_checked_on else None,
             "notes": x.notes, "createdAt": x.created_at, "updatedAt": x.updated_at,
             "version": x.version},
        )  # fmt: skip

    # ---- Essays ------------------------------------------------------------------------

    @staticmethod
    def _essay(d: Doc) -> Essay:
        return Essay(
            essay_id=d["essayId"], student_id=d["studentId"], title=d["title"],
            prompt=d["prompt"], draft=d["draft"], created_at=d["createdAt"],
            updated_at=d["updatedAt"], version=int(d.get("version", 1)),
            active_run_id=d.get("activeRunId"),
        )  # fmt: skip

    async def get_essay(self, actor: ActorContext, essay_id: str) -> Essay | None:
        d = await self._get(actor, "admissionsEssays", essay_id)
        return self._essay(d) if d else None

    async def list_essays(self, actor: ActorContext) -> Sequence[Essay]:
        return [self._essay(d) for d in await self._list(actor, "admissionsEssays", "createdAt")]

    def save_essay(self, actor: ActorContext, e: Essay) -> None:
        _check(actor, e.student_id)
        self._txn.set(
            paths.sub(actor, "admissionsEssays", e.essay_id),
            {"essayId": e.essay_id, "studentId": e.student_id, "title": e.title,
             "prompt": e.prompt, "draft": e.draft, "createdAt": e.created_at,
             "updatedAt": e.updated_at, "version": e.version, "activeRunId": e.active_run_id},
        )  # fmt: skip

    # ---- Feedback ----------------------------------------------------------------------

    @staticmethod
    def _feedback(d: Doc) -> FeedbackRequest:
        return FeedbackRequest(
            feedback_id=d["feedbackId"], student_id=d["studentId"], essay_id=d["essayId"],
            essay_version=int(d["essayVersion"]), kind=FeedbackKind(d["kind"]),
            run_id=d["runId"], created_at=d["createdAt"],
            items=tuple(
                FeedbackItem(type=FeedbackItemType(i["type"]), text=i["text"],
                             fact_ids=tuple(i.get("factIds", ())))
                for i in d.get("items", ())
            ),
            model_version=d.get("modelVersion"), completed_at=d.get("completedAt"),
        )  # fmt: skip

    async def get_feedback(self, actor: ActorContext, feedback_id: str) -> FeedbackRequest | None:
        d = await self._get(actor, "admissionsFeedback", feedback_id)
        return self._feedback(d) if d else None

    async def list_feedback(self, actor: ActorContext) -> Sequence[FeedbackRequest]:
        docs = await self._list(actor, "admissionsFeedback", "createdAt")
        return [self._feedback(d) for d in docs]

    def save_feedback(self, actor: ActorContext, f: FeedbackRequest) -> None:
        _check(actor, f.student_id)
        self._txn.set(
            paths.sub(actor, "admissionsFeedback", f.feedback_id),
            {"feedbackId": f.feedback_id, "studentId": f.student_id, "essayId": f.essay_id,
             "essayVersion": f.essay_version, "kind": f.kind.value, "runId": f.run_id,
             "createdAt": f.created_at,
             "items": [{"type": i.type.value, "text": i.text, "factIds": list(i.fact_ids)}
                       for i in f.items],
             "modelVersion": f.model_version, "completedAt": f.completed_at},
        )  # fmt: skip
