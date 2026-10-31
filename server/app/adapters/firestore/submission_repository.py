from __future__ import annotations

from app.adapters.firestore import paths
from app.adapters.firestore.documents import Doc, DocTxn, Filter
from app.adapters.firestore.paging import paged_query
from app.domain.types.actor import ActorContext
from app.domain.types.common import PageRequest, PaginatedResponse
from app.domain.types.submission import Submission, SubmissionAnswer


def submission_from_doc(doc: Doc) -> Submission:
    return Submission(
        submission_id=doc["submissionId"],
        student_id=doc["studentId"],
        session_id=doc["sessionId"],
        question_id=doc["questionId"],
        question_version=doc["questionVersion"],
        answer=SubmissionAnswer(
            text=doc["answer"]["text"], file_ids=tuple(doc["answer"].get("fileIds", []))
        ),
        supersedes_submission_id=doc.get("supersedesSubmissionId"),
        run_id=doc["runId"],
        created_at=doc["createdAt"],
    )


class FirestoreSubmissionStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext, submission_id: str) -> Submission | None:
        doc = await self._txn.get(paths.sub(actor, "submissions", submission_id))
        return submission_from_doc(doc) if doc else None

    async def list_for_session(
        self, actor: ActorContext, session_id: str, page: PageRequest
    ) -> PaginatedResponse[Submission]:
        return await paged_query(
            self._txn,
            paths.sub(actor, "submissions"),
            filters=[Filter("sessionId", "==", session_id)],
            order_by=("createdAt", "submissionId"),
            page=page,
            decode=submission_from_doc,
        )

    def create(self, actor: ActorContext, s: Submission) -> None:
        if s.student_id != actor.student_id:
            raise ValueError("submission does not belong to actor")
        self._txn.set(
            paths.sub(actor, "submissions", s.submission_id),
            {
                "submissionId": s.submission_id,
                "studentId": s.student_id,
                "sessionId": s.session_id,
                "questionId": s.question_id,
                "questionVersion": s.question_version,
                "answer": {"text": s.answer.text, "fileIds": list(s.answer.file_ids)},
                "supersedesSubmissionId": s.supersedes_submission_id,
                "runId": s.run_id,
                "createdAt": s.created_at,
            },
        )
