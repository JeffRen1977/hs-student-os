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
