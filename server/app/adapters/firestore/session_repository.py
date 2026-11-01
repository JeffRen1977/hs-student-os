from __future__ import annotations

from app.adapters.firestore import paths
from app.adapters.firestore.documents import Doc, DocTxn, Filter
from app.adapters.firestore.paging import paged_query
from app.domain.ports.repositories import SessionQuery
from app.domain.types.actor import ActorContext
from app.domain.types.common import PageRequest, PaginatedResponse
from app.domain.types.session import (
    ContextVersion,
    Session,
    SessionActivity,
    SessionStatus,
    completion_for,
)


def session_to_doc(s: Session) -> Doc:
    return {
        "sessionId": s.session_id,
        "studentId": s.student_id,
        "taskId": s.task_id,
        "courseId": s.course_id,
        "status": s.status.value,
        "activeRunId": s.active_run_id,
        "contextVersion": {"pack": s.context_version.pack, "workflow": s.context_version.workflow},
        "agentSkills": list(s.agent_skills),
        "hasAcceptedAssessment": s.has_accepted_assessment,
        "activity": (
            {
                "questionId": s.activity.question_id,
                "questionVersion": s.activity.question_version,
                "rubricId": s.activity.rubric_id,
                "rubricVersion": s.activity.rubric_version,
            }
            if s.activity
            else None
        ),
        "serverHintCount": s.server_hint_count,
        "version": s.version,
        "createdAt": s.created_at,
        "updatedAt": s.updated_at,
    }


def session_from_doc(doc: Doc) -> Session:
    status = SessionStatus(doc["status"])
    active = doc.get("activeRunId")
    accepted = bool(doc.get("hasAcceptedAssessment", False))
    act = doc.get("activity")
    return Session(
        session_id=doc["sessionId"],
        student_id=doc["studentId"],
        task_id=doc["taskId"],
        course_id=doc["courseId"],
        status=status,
        active_run_id=active,
        context_version=ContextVersion(
            pack=doc["contextVersion"]["pack"], workflow=doc["contextVersion"]["workflow"]
        ),
        # Completion eligibility is always recomputed from stored facts, never stored.
        completion=completion_for(status, active, accepted),
        version=int(doc["version"]),
        agent_skills=tuple(doc.get("agentSkills", [])),
        has_accepted_assessment=accepted,
        activity=(
            SessionActivity(
                question_id=act["questionId"],
                question_version=act["questionVersion"],
                rubric_id=act["rubricId"],
                rubric_version=act["rubricVersion"],
            )
            if act
            else None
        ),
        server_hint_count=int(doc.get("serverHintCount", 0)),
        created_at=doc.get("createdAt"),
        updated_at=doc.get("updatedAt"),
    )


class FirestoreSessionStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext, session_id: str) -> Session | None:
        doc = await self._txn.get(paths.sub(actor, "sessions", session_id))
        return session_from_doc(doc) if doc else None

    async def list(
        self, actor: ActorContext, query: SessionQuery, page: PageRequest
    ) -> PaginatedResponse[Session]:
        filters: list[Filter] = []
        if query.task_id is not None:
            filters.append(Filter("taskId", "==", query.task_id))
        if query.course_id is not None:
            filters.append(Filter("courseId", "==", query.course_id))
        if query.status is not None:
            filters.append(Filter("status", "==", query.status.value))
        return await paged_query(
            self._txn,
            paths.sub(actor, "sessions"),
            filters=filters,
            order_by=("createdAt", "sessionId"),
            page=page,
            decode=session_from_doc,
        )

    def save(self, actor: ActorContext, session: Session) -> None:
        if session.student_id != actor.student_id:
            raise ValueError("session does not belong to actor")
        self._txn.set(paths.sub(actor, "sessions", session.session_id), session_to_doc(session))
