"""Aggregate course metrics (Step 34.4, BACKEND.md §3).

    courseMetrics/{courseId}                            the aggregate (no student data)
    students/{studentId}/metricsMembership/{courseId}  "this student is counted" marker

The marker lives in the student's own subtree, so counting distinct students never
writes a student id anywhere an author-facing read can reach.
"""

from __future__ import annotations

from datetime import datetime

from app.adapters.firestore import paths
from app.adapters.firestore.documents import Doc, DocTxn
from app.domain.types.actor import ActorContext
from app.domain.types.course_metrics import CourseMetrics, CriterionTotals

METRICS = "courseMetrics"


def metrics_path(course_id: str) -> str:
    if not course_id or "/" in course_id:
        raise ValueError("invalid course id")
    return f"{METRICS}/{course_id}"


def metrics_to_doc(m: CourseMetrics) -> Doc:
    return {
        "courseId": m.course_id,
        "students": m.students,
        "assessments": m.assessments,
        "byStatus": dict(m.by_status),
        "criteria": {
            k: {"earned": t.earned, "possible": t.possible, "count": t.count}
            for k, t in m.criteria.items()
        },
        "updatedAt": m.updated_at,
    }


def metrics_from_doc(d: Doc) -> CourseMetrics:
    return CourseMetrics(
        course_id=d["courseId"],
        students=int(d.get("students", 0)),
        assessments=int(d.get("assessments", 0)),
        by_status={k: int(v) for k, v in d.get("byStatus", {}).items()},
        criteria={
            k: CriterionTotals(
                earned=int(v["earned"]), possible=int(v["possible"]), count=int(v["count"])
            )
            for k, v in d.get("criteria", {}).items()
        },
        updated_at=d.get("updatedAt"),
    )


class FirestoreCourseMetricsStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, course_id: str) -> CourseMetrics | None:
        doc = await self._txn.get(metrics_path(course_id))
        return metrics_from_doc(doc) if doc else None

    def save(self, metrics: CourseMetrics) -> None:
        self._txn.set(metrics_path(metrics.course_id), metrics_to_doc(metrics))

    async def is_member(self, actor: ActorContext, course_id: str) -> bool:
        return await self._txn.get(paths.sub(actor, "metricsMembership", course_id)) is not None

    def mark_member(self, actor: ActorContext, course_id: str, now: datetime) -> None:
        self._txn.set(
            paths.sub(actor, "metricsMembership", course_id),
            {"courseId": course_id, "countedAt": now},
        )
