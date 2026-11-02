from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ActorRole(StrEnum):
    STUDENT = "student"
    SERVICE = "service"  # worker / scheduler identities (OIDC), never a browser
    ADMIN = "admin"  # back-office tooling, e.g. entitlement management
    AUTHOR = "author"  # course-package author, member of one author organization
    PLATFORM_REVIEWER = "platform_reviewer"  # approves, activates and retires packages


class Permission(StrEnum):
    TWIN_READ = "twin:read"
    TWIN_WRITE = "twin:write"
    LEARNING_READ = "learning:read"
    LEARNING_COMMAND = "learning:command"
    RUN_EXECUTE = "run:execute"
    ENTITLEMENTS_WRITE = "entitlements:write"
    PACKAGES_AUTHOR = "packages:author"
    PACKAGES_REVIEW = "packages:review"


STUDENT_PERMISSIONS = frozenset(
    {
        Permission.TWIN_READ,
        Permission.TWIN_WRITE,
        Permission.LEARNING_READ,
        Permission.LEARNING_COMMAND,
    }
)

SERVICE_PERMISSIONS = frozenset({Permission.LEARNING_READ, Permission.RUN_EXECUTE})

SERVICE_ACTOR_PREFIX = "svc:"

PLATFORM_ROLE_PERMISSIONS: dict[ActorRole, frozenset[Permission]] = {
    ActorRole.AUTHOR: frozenset({Permission.PACKAGES_AUTHOR}),
    ActorRole.PLATFORM_REVIEWER: frozenset({Permission.PACKAGES_REVIEW}),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class ActorContext:
    """Who is acting, on behalf of which student, with what permissions.

    Every domain operation and repository call receives one. `student_id` always comes
    from a verified identity (or a service job bound to a student), never a request body.
    """

    actor_id: str
    student_id: str
    role: ActorRole
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    request_id: str | None = None

    def __post_init__(self) -> None:
        if not self.actor_id or not self.student_id:
            raise ValueError("actor_id and student_id are required")
        if self.role is ActorRole.STUDENT and self.actor_id != self.student_id:
            raise ValueError("a student actor may only act for their own student_id")
        if self.role is ActorRole.SERVICE and not self.actor_id.startswith(SERVICE_ACTOR_PREFIX):
            raise ValueError("service actor ids start with 'svc:' so they never collide with uids")
        if self.role is ActorRole.STUDENT and self.actor_id.startswith(SERVICE_ACTOR_PREFIX):
            raise ValueError("student ids may not use the service prefix")

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions

    @classmethod
    def for_student(cls, student_id: str, request_id: str | None = None) -> ActorContext:
        return cls(
            actor_id=student_id,
            student_id=student_id,
            role=ActorRole.STUDENT,
            permissions=STUDENT_PERMISSIONS,
            request_id=request_id,
        )

    @classmethod
    def for_service(
        cls,
        service_name: str,
        student_id: str,
        *,
        permissions: frozenset[Permission] = SERVICE_PERMISSIONS,
        request_id: str | None = None,
    ) -> ActorContext:
        """Internal worker/scheduler identity bound to one student. Never built from a
        student token: only worker entry points that verified a service identity call it."""
        return cls(
            actor_id=SERVICE_ACTOR_PREFIX + service_name,
            student_id=student_id,
            role=ActorRole.SERVICE,
            permissions=permissions,
            request_id=request_id,
        )

    def require(self, permission: Permission) -> None:
        if permission not in self.permissions:
            # Imported lazily to keep this module dependency-free.
            from app.domain.errors import DomainError, ErrorCode

            raise DomainError(ErrorCode.FORBIDDEN, f"missing permission {permission.value}")


@dataclass(frozen=True, slots=True, kw_only=True)
class PlatformActor:
    """An author or platform reviewer (Step 26). Deliberately a different type from
    `ActorContext`: it has no `student_id`, so it cannot be passed to any student store or
    learning service, and authors never see student data.

    Authors belong to exactly one author organization (`org_id`) and see only that
    organization's packages. Reviewers act for the platform and have no organization.
    """

    actor_id: str
    role: ActorRole
    org_id: str | None
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    request_id: str | None = None

    def __post_init__(self) -> None:
        if not self.actor_id or self.actor_id.startswith(SERVICE_ACTOR_PREFIX):
            raise ValueError("platform actors need a real uid")
        if self.role not in PLATFORM_ROLE_PERMISSIONS:
            raise ValueError("platform actors are authors or platform reviewers")
        if (self.role is ActorRole.AUTHOR) != (self.org_id is not None):
            raise ValueError("authors belong to one organization; reviewers to none")

    @classmethod
    def for_member(
        cls, uid: str, role: ActorRole, org_id: str | None, request_id: str | None = None
    ) -> PlatformActor:
        return cls(
            actor_id=uid,
            role=role,
            org_id=org_id,
            permissions=PLATFORM_ROLE_PERMISSIONS[role],
            request_id=request_id,
        )

    def require(self, permission: Permission) -> None:
        if permission not in self.permissions:
            from app.domain.errors import DomainError, ErrorCode

            raise DomainError(ErrorCode.FORBIDDEN, f"missing permission {permission.value}")
