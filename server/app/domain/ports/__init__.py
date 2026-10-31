"""Repository protocols (ports). Adapters in `app.adapters` implement these.

Every method takes an ActorContext and is scoped to `actor.student_id`. Implementations
must return None / raise NOT_FOUND for another student's resources, never leak them.
"""

from app.domain.ports.repositories import (
    AssessmentRepository,
    CourseRepository,
    EventRepository,
    IdempotencyRepository,
    RunRepository,
    SessionRepository,
    StudentRepository,
    SubmissionRepository,
    TaskRepository,
)

__all__ = [
    "AssessmentRepository",
    "CourseRepository",
    "EventRepository",
    "IdempotencyRepository",
    "RunRepository",
    "SessionRepository",
    "StudentRepository",
    "SubmissionRepository",
    "TaskRepository",
]
