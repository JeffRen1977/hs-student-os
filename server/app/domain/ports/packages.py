"""Ports for course-package authoring and review (Step 26).

Package records live outside any student's subtree. Their stores take a `PlatformActor`
or nothing at all; they can never reach student data, and student stores can never be
called with a platform actor (different types).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol

from app.domain.types.common import IdempotencyRecord
from app.domain.types.course_metrics import CourseMetrics
from app.domain.types.package import (
    PackageCourse,
    PackageStatus,
    PackageVersion,
    PlatformMember,
    ValidationReport,
)


class PackageCheck(Protocol):
    """What the validator tells the domain about an uploaded package."""

    @property
    def report(self) -> ValidationReport: ...

    @property
    def course_id(self) -> str | None: ...

    @property
    def version(self) -> str | None: ...

    @property
    def title(self) -> str: ...

    @property
    def canonical_json(self) -> str: ...

    @property
    def content_hash(self) -> str: ...


class PackageValidator(Protocol):
    def validate(self, raw: Mapping[str, Any]) -> PackageCheck: ...


class PackageCourseStore(Protocol):
    async def get(self, course_id: str) -> PackageCourse | None: ...

    def save(self, course: PackageCourse) -> None: ...


class PackageVersionStore(Protocol):
    async def get(self, course_id: str, version: str) -> PackageVersion | None: ...

    async def list_for_course(self, course_id: str) -> Sequence[PackageVersion]: ...

    async def list_for_org(self, org_id: str) -> Sequence[PackageVersion]: ...

    async def list_by_status(
        self, statuses: Sequence[PackageStatus]
    ) -> Sequence[PackageVersion]: ...

    def save(self, version: PackageVersion) -> None: ...


class PlatformIdempotencyStore(Protocol):
    """Idempotency records of one platform member (`platformMembers/{uid}/idempotency`)."""

    async def get(self, actor_id: str, key_hash: str) -> IdempotencyRecord | None: ...

    def save(self, actor_id: str, record: IdempotencyRecord) -> None: ...


class CourseMetricsReader(Protocol):
    """Aggregate metrics only (Step 34.4): no path from here reaches a student document."""

    async def get(self, course_id: str) -> CourseMetrics | None: ...


class PackageTx(Protocol):
    @property
    def courses(self) -> PackageCourseStore: ...

    @property
    def versions(self) -> PackageVersionStore: ...

    @property
    def idempotency(self) -> PlatformIdempotencyStore: ...

    @property
    def metrics(self) -> CourseMetricsReader: ...


class PackageUnitOfWork(Protocol):
    async def transaction[T](self, fn: Callable[[PackageTx], Awaitable[T]]) -> T: ...


class PlatformDirectory(Protocol):
    """`platformMembers/{uid}` → role and organization. Unknown uid → None."""

    async def resolve(self, uid: str) -> PlatformMember | None: ...


class ContentActivation(Protocol):
    """Reloads servable package versions into the runtime registry after a change."""

    async def refresh(self) -> None: ...
