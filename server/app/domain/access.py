"""Course access policy: published courses are open to every student.

Admins publish reviewer-approved packages. Students explicitly enroll before learning.
"""

from __future__ import annotations

from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.catalog import CourseCatalog
from app.domain.ports.repositories import Tx
from app.domain.types.actor import ActorContext
from app.domain.types.common import Availability
from app.domain.types.course import (
    CourseDefinition,
    CourseEnrollment,
    EnrollmentStatus,
)


def is_enrolled(enrollment: CourseEnrollment | None) -> bool:
    return enrollment is not None and enrollment.status is EnrollmentStatus.ACTIVE


def require_known_course(catalog: CourseCatalog, course_id: str) -> CourseDefinition:
    course = catalog.get(course_id)
    if course is None:
        raise DomainError(ErrorCode.NOT_FOUND, "Course not found.")
    return course


def check_available(course: CourseDefinition) -> None:
    if course.availability is Availability.RETIRED:
        raise DomainError(ErrorCode.COURSE_NOT_AVAILABLE, "This course has been retired.")
    if not course.is_active:
        raise DomainError(ErrorCode.COURSE_NOT_AVAILABLE, "This course is not available yet.")


async def require_course_access(
    tx: Tx, actor: ActorContext, catalog: CourseCatalog, course_id: str
) -> CourseDefinition:
    """Full check for learning activity: active course and active enrollment.

    Reading the enrollment inside the caller's transaction also makes concurrent unenroll
    and session/command creation conflict instead of interleaving.
    """
    course = require_known_course(catalog, course_id)
    check_available(course)
    if not is_enrolled(await tx.enrollments.get(actor, course_id)):
        raise DomainError(ErrorCode.COURSE_NOT_ENROLLED, "Enroll in this course first.")
    return course
