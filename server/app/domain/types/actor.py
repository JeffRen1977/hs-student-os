from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ActorRole(StrEnum):
    STUDENT = "student"
    SERVICE = "service"  # worker / scheduler identities (OIDC), never a browser
    ADMIN = "admin"  # back-office tooling, e.g. entitlement management


class Permission(StrEnum):
    TWIN_READ = "twin:read"
    TWIN_WRITE = "twin:write"
    LEARNING_READ = "learning:read"
    LEARNING_COMMAND = "learning:command"
    RUN_EXECUTE = "run:execute"
    ENTITLEMENTS_WRITE = "entitlements:write"


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
