from __future__ import annotations

from datetime import date, datetime

from app.adapters.firestore import paths
from app.adapters.firestore.documents import Doc, DocTxn, Filter
from app.adapters.firestore.paging import paged_query
from app.domain.ports.repositories import TaskQuery
from app.domain.types.actor import ActorContext
from app.domain.types.common import AgentType, PageRequest, PaginatedResponse, StudyMode, TaskType
from app.domain.types.task import SkipReason, Task, TaskReason, TaskReasonCode, TaskStatus


def task_to_doc(task: Task) -> Doc:
    return {
        "taskId": task.task_id,
        "studentId": task.student_id,
        "agent": task.agent.value,
        "courseId": task.course_id,
        "taskType": task.task_type.value,
        "mode": task.mode.value,
        "title": task.title,
        "durationMin": task.duration_min,
        # ISO local dates sort lexically, so range/order queries work on the string.
        "scheduledDate": task.scheduled_date.isoformat(),
        "status": task.status.value,
        "version": task.version,
        "reason": {
            "code": task.reason.code.value,
            "sourceEventIds": list(task.reason.source_event_ids),
            "explanation": task.reason.explanation,
        },
        "studentLocked": task.student_locked,
        "openSessionId": task.open_session_id,
        "questionId": task.question_id,
        "dueDate": task.due_date.isoformat() if task.due_date else None,
        "skipReason": task.skip_reason.value if task.skip_reason else None,
    }


def task_from_doc(doc: Doc) -> Task:
    return Task(
        task_id=doc["taskId"],
        student_id=doc["studentId"],
        agent=AgentType(doc["agent"]),
        course_id=doc["courseId"],
        task_type=TaskType(doc["taskType"]),
        mode=StudyMode(doc["mode"]),
        title=doc["title"],
        duration_min=int(doc["durationMin"]),
        scheduled_date=date.fromisoformat(doc["scheduledDate"]),
        status=TaskStatus(doc["status"]),
        version=int(doc["version"]),
        reason=TaskReason(
            code=TaskReasonCode(doc["reason"]["code"]),
            source_event_ids=tuple(doc["reason"].get("sourceEventIds", [])),
            explanation=doc["reason"].get("explanation", ""),
        ),
        student_locked=bool(doc.get("studentLocked", False)),
        open_session_id=doc.get("openSessionId"),
        question_id=doc.get("questionId"),
        due_date=date.fromisoformat(doc["dueDate"]) if doc.get("dueDate") else None,
        skip_reason=SkipReason(doc["skipReason"]) if doc.get("skipReason") else None,
    )


class FirestoreTaskStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext, task_id: str) -> Task | None:
        doc = await self._txn.get(paths.sub(actor, "tasks", task_id))
        return task_from_doc(doc) if doc else None

    async def list(
        self, actor: ActorContext, query: TaskQuery, page: PageRequest
    ) -> PaginatedResponse[Task]:
        if query.course_ids is not None and not query.course_ids:
            return PaginatedResponse(items=[], next_cursor=None)
        filters: list[Filter] = []
        if query.scheduled_date is not None:
            filters.append(Filter("scheduledDate", "==", query.scheduled_date.isoformat()))
        if query.status is not None:
            filters.append(Filter("status", "==", query.status.value))
        if query.course_ids is not None:
            filters.append(Filter("courseId", "in", list(query.course_ids)))
        return await paged_query(
            self._txn,
            paths.sub(actor, "tasks"),
            filters=filters,
            order_by=("scheduledDate", "taskId"),
            page=page,
            decode=task_from_doc,
        )

    def save(self, actor: ActorContext, task: Task, *, now: datetime) -> None:
        if task.student_id != actor.student_id:
            raise ValueError("task does not belong to actor")
        self._txn.set(
            paths.sub(actor, "tasks", task.task_id), {**task_to_doc(task), "updatedAt": now}
        )
