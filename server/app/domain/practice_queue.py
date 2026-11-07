"""Practice top-up: give a student the next sets in a course's practice order (BACKEND.md §9).

A course's practice order is its package's starter tasks followed by its practice sequence.
Whenever a student has fewer than `TARGET_OPEN_PER_COURSE` unfinished tasks (PLANNED or
IN_PROGRESS) in a course, the next questions in that order that the student has never had
a task for become new PLANNED tasks (reason NEXT_PRACTICE), placed with the same capacity
rule as any new task. Completed and skipped questions are never offered again.

It runs inside the caller's transaction: the planning commit (every enrolled course) and
the session-completion commit (that session's course). It only uses data the package
declares; there is no course-specific logic. A course that is not active, a student
without access or not enrolled, and a question the course does not currently serve (for
example, unreviewed content where reviewed content is required) get nothing.

Queries inside a transaction do not see the transaction's own writes, so callers pass the
tasks they changed (`known`) and receive the tasks this function created.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

from app.domain.access import is_enrolled, is_entitled
from app.domain.planner_service import all_tasks, local_today, place_new_task
from app.domain.ports.catalog import CourseCatalog
from app.domain.ports.content import SubjectPackRegistry
from app.domain.ports.repositories import Tx
from app.domain.ports.runtime import IdFactory
from app.domain.types.actor import ActorContext
from app.domain.types.student import Student
from app.domain.types.task import Task, TaskReason, TaskReasonCode, TaskStatus

TARGET_OPEN_PER_COURSE = 2
OPEN_STATUSES = frozenset({TaskStatus.PLANNED, TaskStatus.IN_PROGRESS})


def _merge(queried: Iterable[Task], known: Iterable[Task]) -> list[Task]:
    by_id = {t.task_id: t for t in queried}
    by_id.update({t.task_id: t for t in known})
    return list(by_id.values())


async def top_up_practice(
    tx: Tx,
    actor: ActorContext,
    *,
    catalog: CourseCatalog,
    packs: SubjectPackRegistry,
    ids: IdFactory,
    student: Student,
    course_ids: Iterable[str],
    now: datetime,
    known: Sequence[Task] = (),
) -> list[Task]:
    """Create the next practice tasks for `course_ids`; return the tasks created."""
    tasks = _merge(await all_tasks(tx, actor), known)
    entitlements = await tx.students.get_entitlements(actor)
    today = local_today(now, student.preferences.timezone)
    weekly = student.preferences.weekly_available_minutes
    created: list[Task] = []
    for course_id in sorted(set(course_ids)):
        course = catalog.get(course_id)
        if course is None or not course.is_active or not course.practice_order:
            continue
        if not is_entitled(entitlements, course):
            continue
        if not is_enrolled(await tx.enrollments.get(actor, course_id)):
            continue
        mine = [t for t in tasks if t.course_id == course_id]
        open_count = sum(t.status in OPEN_STATUSES for t in mine)
        had = {t.question_id for t in mine if t.question_id}
        for spec in course.practice_order:
            if open_count >= TARGET_OPEN_PER_COURSE:
                break
            if spec.question_id in had or packs.question(course_id, spec.question_id) is None:
                continue
            place = place_new_task(today, weekly, [*tasks, *created], spec.duration_min)
            task = Task(
                task_id=ids.new("task"),
                student_id=actor.student_id,
                agent=course.agent.agent_type,
                course_id=course_id,
                task_type=spec.task_type,
                mode=spec.mode,
                title=spec.title,
                duration_min=spec.duration_min,
                scheduled_date=place.scheduled_date,
                status=TaskStatus.PLANNED,
                version=1,
                reason=TaskReason(
                    code=TaskReasonCode.NEXT_PRACTICE,
                    explanation=f"Next practice set in {course.name}. {place.explanation}",
                ),
                question_id=spec.question_id,
            )
            tx.tasks.save(actor, task, now=now)
            created.append(task)
            had.add(spec.question_id)
            open_count += 1
    return created
