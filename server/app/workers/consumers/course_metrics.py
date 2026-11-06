"""Course metrics consumer (Step 34.4): folds each `assessment.completed` into the
course's aggregate. Exactly once per event: the receipt, the aggregate and the
distinct-student marker are written in one transaction (ConsumerRunner).

Only aggregate numbers leave the student's subtree. A regrade (a superseding
assessment) is counted as another assessment; per-criterion totals are a description of
grading activity, not of any student's mastery.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

from app.domain.ports.repositories import Tx
from app.domain.types.actor import ActorContext
from app.domain.types.assessment import AssessmentStatus
from app.domain.types.consumer import ReceiptOutcome
from app.domain.types.course_metrics import CourseMetrics, CriterionTotals
from app.domain.types.event import DomainEvent, EventType
from app.workers.consumers.base import has_receipt, write_receipt

NAME = "course-metrics"
TARGET = "course"  # receipts are per (consumer, event, target); one target per event here


class CourseMetricsConsumer:
    name = NAME
    subscribes = frozenset({EventType.ASSESSMENT_COMPLETED})

    async def handle(self, tx: Tx, actor: ActorContext, event: DomainEvent, now: datetime) -> None:
        if await has_receipt(tx, actor, NAME, event.event_id, TARGET):
            return
        assessment_id = event.payload.get("assessmentId")
        assessment = (
            await tx.assessments.get(actor, assessment_id)
            if isinstance(assessment_id, str)
            else None
        )
        session = await tx.sessions.get(actor, assessment.session_id) if assessment else None
        if assessment is None or session is None:
            write_receipt(
                tx, actor, consumer=NAME, event=event, target_skill_id=TARGET,
                outcome=ReceiptOutcome.NO_ACTION, reason="assessment_not_found", now=now,
            )  # fmt: skip
            return
        course_id = session.course_id
        current = await tx.course_metrics.get(course_id) or CourseMetrics(course_id=course_id)
        students = current.students
        if not await tx.course_metrics.is_member(actor, course_id):
            tx.course_metrics.mark_member(actor, course_id, now)
            students += 1
        by_status = dict(current.by_status)
        by_status[assessment.status.value] = by_status.get(assessment.status.value, 0) + 1
        criteria = dict(current.criteria)
        if assessment.status is AssessmentStatus.ACCEPTED:
            for r in assessment.rubric_results:
                key = f"{assessment.rubric_id or 'rubric'}:{r.criterion_id}"
                t = criteria.get(key, CriterionTotals())
                criteria[key] = CriterionTotals(
                    earned=t.earned + r.earned, possible=t.possible + r.possible,
                    count=t.count + 1,
                )  # fmt: skip
        tx.course_metrics.save(
            dataclasses.replace(
                current,
                students=students,
                assessments=current.assessments + 1,
                by_status=by_status,
                criteria=criteria,
                updated_at=now,
            )
        )
        write_receipt(
            tx, actor, consumer=NAME, event=event, target_skill_id=TARGET,
            outcome=ReceiptOutcome.APPLIED, reason="counted", now=now,
        )  # fmt: skip
