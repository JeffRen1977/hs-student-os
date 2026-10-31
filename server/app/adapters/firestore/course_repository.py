from __future__ import annotations

from collections.abc import Sequence

from app.adapters.firestore import paths
from app.adapters.firestore.documents import Doc, DocTxn, Filter, QuerySpec
from app.domain.types.actor import ActorContext
from app.domain.types.course import CourseEnrollment, EnrollmentStatus

ENROLLMENT_LIMIT = 100


def enrollment_from_doc(student_id: str, doc: Doc) -> CourseEnrollment:
    return CourseEnrollment(
        student_id=student_id,
        course_id=doc["courseId"],
        status=EnrollmentStatus(doc["status"]),
        enrolled_at=doc["enrolledAt"],
        unenrolled_at=doc.get("unenrolledAt"),
    )


class FirestoreEnrollmentStore:
    """`students/{studentId}/enrollments/{courseId}` — one document per course, reused
    across unenroll/re-enroll so history stays attached."""

    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext, course_id: str) -> CourseEnrollment | None:
        doc = await self._txn.get(paths.sub(actor, "enrollments", course_id))
        return enrollment_from_doc(actor.student_id, doc) if doc else None

    async def list(
        self, actor: ActorContext, *, status: EnrollmentStatus | None = None
    ) -> Sequence[CourseEnrollment]:
        filters = [Filter("status", "==", status.value)] if status else []
        docs = await self._txn.query(
            paths.sub(actor, "enrollments"),
            QuerySpec(filters=filters, order_by=("courseId",), limit=ENROLLMENT_LIMIT),
        )
        return [enrollment_from_doc(actor.student_id, d) for d in docs]

    def save(self, actor: ActorContext, enrollment: CourseEnrollment) -> None:
        if enrollment.student_id != actor.student_id:
            raise ValueError("enrollment does not belong to actor")
        self._txn.set(
            paths.sub(actor, "enrollments", enrollment.course_id),
            {
                "courseId": enrollment.course_id,
                "status": enrollment.status.value,
                "enrolledAt": enrollment.enrolled_at,
                "unenrolledAt": enrollment.unenrolled_at,
            },
        )
