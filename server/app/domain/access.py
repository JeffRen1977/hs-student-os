"""Course access policy: availability, entitlement, and enrollment are separate checks.

Selecting a course in preferences grants nothing. Entitlements are admin-managed; an
enrollment is the student's own choice, allowed only on top of an entitlement.
"""

from __future__ import annotations

from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.catalog import CourseCatalog
from app.domain.ports.repositories import Tx
from app.domain.types.actor import ActorContext
from app.domain.types.course import (
    CourseCategory,
    CourseDefinition,
    CourseEnrollment,
    EnrollmentStatus,
)
from app.domain.types.student import Entitlements


def is_entitled(entitlements: Entitlements, course: CourseDefinition) -> bool:
    match course.category:
        case CourseCategory.AP:
            return course.course_id in entitlements.ap_courses
        case CourseCategory.SAT:
            return entitlements.dsat
        case CourseCategory.ADMISSIONS:
            return entitlements.admissions


def is_enrolled(enrollment: CourseEnrollment | None) -> bool:
    return enrollment is not None and enrollment.status is EnrollmentStatus.ACTIVE


def require_known_course(catalog: CourseCatalog, course_id: str) -> CourseDefinition:
    course = catalog.get(course_id)
    if course is None:
        raise DomainError(ErrorCode.NOT_FOUND, "Course not found.")
    return course


def check_available_and_entitled(course: CourseDefinition, entitlements: Entitlements) -> None:
    if not course.is_active:
        raise DomainError(ErrorCode.COURSE_NOT_AVAILABLE, "This course is not available yet.")
    if not is_entitled(entitlements, course):
        raise DomainError(
            ErrorCode.COURSE_ACCESS_REQUIRED, "Access to this course has not been granted."
        )


async def require_course_access(
    tx: Tx, actor: ActorContext, catalog: CourseCatalog, course_id: str
) -> CourseDefinition:
    """Full check for learning activity: active pack, entitlement, and active enrollment.

    Reading the enrollment inside the caller's transaction also makes concurrent unenroll
    and session/command creation conflict instead of interleaving.
    """
    course = require_known_course(catalog, course_id)
    check_available_and_entitled(course, await tx.students.get_entitlements(actor))
    if not is_enrolled(await tx.enrollments.get(actor, course_id)):
        raise DomainError(ErrorCode.COURSE_NOT_ENROLLED, "Enroll in this course first.")
    return course
