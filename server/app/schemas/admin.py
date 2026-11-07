"""Course access administration contract (Step 42, API.md §6.5.6).

The `studentId` in these routes is the student being administered, never the caller: the
caller's identity comes only from the verified token (a platform admin).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.domain.types.common import Availability
from app.domain.types.course import CourseCategory, EnrollmentStatus
from app.schemas.common import ApiModel, CourseId, OpaqueId, RequestModel, UtcDatetime

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class AccessChangeRequest(RequestModel):
    course_id: CourseId
    reason: Reason


class BulkAccessRequest(RequestModel):
    student_ids: list[OpaqueId] = Field(min_length=1, max_length=200)
    course_id: CourseId
    change: Literal["grant", "revoke"]
    reason: Reason


class AccessRecordView(ApiModel):
    ap_courses: list[str]
    courses: list[str]
    admissions: bool
    updated_at: UtcDatetime | None
    updated_by: str | None


class EnrollmentView(ApiModel):
    status: EnrollmentStatus
    enrolled_at: UtcDatetime | None
    unenrolled_at: UtcDatetime | None


class CourseAccessView(ApiModel):
    course_id: CourseId
    name: str
    category: CourseCategory
    availability: Availability
    granted: bool
    enrollment: EnrollmentView | None


class AuditEntryView(ApiModel):
    audit_id: OpaqueId
    course_id: str
    change: Literal["grant", "revoke"]
    reason: str
    actor_id: str
    at: UtcDatetime


class StudentAccessView(ApiModel):
    student_id: OpaqueId
    display_name: str
    access: AccessRecordView
    courses: list[CourseAccessView]
    audit: list[AuditEntryView]


class AccessChangeView(ApiModel):
    changed: bool
    audit_id: OpaqueId | None
    access: StudentAccessView


class BulkResultView(ApiModel):
    student_id: OpaqueId
    status: Literal["changed", "unchanged", "failed"]
    audit_id: OpaqueId | None = None
    error_code: str | None = None
    message: str | None = None


class BulkAccessView(ApiModel):
    results: list[BulkResultView]
    changed: int
    unchanged: int
    failed: int
