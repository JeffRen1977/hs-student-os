"""Course packages: versions, the review workflow and its audit trail (Step 26).

A course package is data only. Each version moves through a strict state machine and every
change is recorded with who made it and when, so a course reaches students only through
validation plus a platform reviewer's approval.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class PackageStatus(StrEnum):
    DRAFT = "draft"  # uploaded with a validator report; the author may replace it
    SUBMITTED = "submitted"  # waiting for a platform reviewer; immutable from here on
    APPROVED = "approved"  # reviewer approved; not yet served to students
    ACTIVE = "active"  # the version new sessions use
    SUPERSEDED = "superseded"  # replaced by a newer active version; still serves pinned runs
    REJECTED = "rejected"  # reviewer rejected with notes; a new version is needed
    RETIRED = "retired"  # course retired: no new work; pinned records stay readable


PACKAGE_TRANSITIONS: Mapping[PackageStatus, frozenset[PackageStatus]] = {
    PackageStatus.DRAFT: frozenset({PackageStatus.SUBMITTED}),
    PackageStatus.SUBMITTED: frozenset({PackageStatus.APPROVED, PackageStatus.REJECTED}),
    PackageStatus.APPROVED: frozenset({PackageStatus.ACTIVE}),
    PackageStatus.ACTIVE: frozenset({PackageStatus.SUPERSEDED, PackageStatus.RETIRED}),
    PackageStatus.SUPERSEDED: frozenset(),
    PackageStatus.REJECTED: frozenset(),
    PackageStatus.RETIRED: frozenset(),
}

# Versions the runtime loads: the active one, plus older ones that open sessions or past
# assessments may be pinned to.
SERVABLE_STATUSES = frozenset(
    {PackageStatus.ACTIVE, PackageStatus.SUPERSEDED, PackageStatus.RETIRED}
)


@dataclass(frozen=True, slots=True, kw_only=True)
class PackageIssue:
    """One validator finding, with the path of the offending field."""

    path: str
    code: str
    message: str


@dataclass(frozen=True, slots=True, kw_only=True)
class EvaluationSummary:
    """Evaluation-set results the platform computed at upload.

    Cases on key-scored questions run deterministically (no model). Cases that need model
    grading are counted and left to the reviewer, who must attest them at approval.
    """

    auto_cases: int = 0
    auto_passed: int = 0
    model_cases: int = 0
    failures: Sequence[str] = ()  # caseIds whose result differed from the expectation

    @property
    def auto_all_passed(self) -> bool:
        return self.auto_passed == self.auto_cases


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidationReport:
    validator_version: str
    errors: Sequence[PackageIssue] = ()
    evaluation: EvaluationSummary = field(default_factory=EvaluationSummary)

    @property
    def valid(self) -> bool:
        return not self.errors


@dataclass(frozen=True, slots=True, kw_only=True)
class ReviewDecision:
    reviewer_id: str
    decision: PackageStatus  # APPROVED or REJECTED
    decided_at: datetime
    notes: str
    license_attested: bool = False
    model_evaluation_attested: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class StatusChange:
    from_status: PackageStatus | None
    to_status: PackageStatus
    actor_id: str
    at: datetime
    notes: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class PackageVersion:
    course_id: str
    version: str
    org_id: str
    status: PackageStatus
    title: str
    package_json: str  # the uploaded package, canonical JSON; never edited after submit
    content_hash: str
    report: ValidationReport
    uploaded_by: str
    created_at: datetime
    updated_at: datetime
    review: ReviewDecision | None = None
    history: Sequence[StatusChange] = ()

    @property
    def key(self) -> str:
        return f"{self.course_id}@{self.version}"


class CourseState(StrEnum):
    DRAFTING = "drafting"  # claimed by an organization, nothing active yet
    ACTIVE = "active"
    RETIRED = "retired"


@dataclass(frozen=True, slots=True, kw_only=True)
class PackageCourse:
    """Ownership and the active pointer for one authored courseId."""

    course_id: str
    org_id: str
    state: CourseState
    active_version: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class PlatformMember:
    uid: str
    role: str  # ActorRole value: "author" | "platform_reviewer"
    org_id: str | None


def semver_key(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(p) for p in version.split("."))
    return major, minor, patch
