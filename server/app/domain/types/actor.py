from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ActorRole(StrEnum):
    STUDENT = "student"
    SERVICE = "service"  # worker / scheduler identities (OIDC), never a browser
    ADMIN = "admin"  # publishes reviewer-approved courses for the whole platform
    AUTHOR = "author"  # course-package author, member of one author organization
    PLATFORM_REVIEWER = "platform_reviewer"  # approves or rejects content
    PARENT = "parent"  # reads a scoped summary of a linked student (Step 36)


class Permission(StrEnum):
    TWIN_READ = "twin:read"
    TWIN_WRITE = "twin:write"
    LEARNING_READ = "learning:read"
    LEARNING_COMMAND = "learning:command"
    RUN_EXECUTE = "run:execute"
    ENTITLEMENTS_MANAGE = "entitlements:manage"  # legacy records; no platform role grants this
    PACKAGES_AUTHOR = "packages:author"
    PACKAGES_REVIEW = "packages:review"
    PACKAGES_PUBLISH = "packages:publish"  # admins publish reviewer-approved courses
    SUMMARY_READ = "summary:read"  # parent: the summary projection only (Step 36)


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

# A parent acting on a linked student's data holds exactly the scopes the student granted,
# and those scopes are limited to this set.
PARENT_SCOPES = frozenset({Permission.SUMMARY_READ})

# An admin acting on one student's access holds exactly this (Step 42): no learning
# permission, so no learning service accepts it.
ADMIN_STUDENT_PERMISSIONS = frozenset({Permission.ENTITLEMENTS_MANAGE})

PLATFORM_ROLE_PERMISSIONS: dict[ActorRole, frozenset[Permission]] = {
    ActorRole.AUTHOR: frozenset({Permission.PACKAGES_AUTHOR}),
    ActorRole.PLATFORM_REVIEWER: frozenset({Permission.PACKAGES_REVIEW}),
    ActorRole.ADMIN: frozenset({Permission.PACKAGES_PUBLISH}),
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
        if self.role is ActorRole.ADMIN and (
            self.actor_id == self.student_id
            or self.actor_id.startswith(SERVICE_ACTOR_PREFIX)
            or not self.permissions <= ADMIN_STUDENT_PERMISSIONS
        ):
            raise ValueError("an admin acts on one student's access with entitlements:manage only")
        if self.role is ActorRole.PARENT and (
            self.actor_id == self.student_id or not self.permissions <= PARENT_SCOPES
        ):
            raise ValueError("a parent acts for a linked student with summary scopes only")

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

    @classmethod
    def for_admin(
        cls, admin_uid: str, student_id: str, request_id: str | None = None
    ) -> ActorContext:
        """Only built by AccessService after it checked the platform admin's
        `entitlements:manage` permission (Step 42). It can read and write one student's
        access record and audit; it holds no learning permission."""
        return cls(
            actor_id=admin_uid,
            student_id=student_id,
            role=ActorRole.ADMIN,
            permissions=ADMIN_STUDENT_PERMISSIONS,
            request_id=request_id,
        )

    @classmethod
    def for_parent(
        cls,
        parent_uid: str,
        student_id: str,
        scopes: frozenset[Permission],
        request_id: str | None = None,
    ) -> ActorContext:
        """Only built by ParentService, inside the transaction that verified an active link
        granting `scopes` (Step 36). Never from a request body."""
        return cls(
            actor_id=parent_uid,
            student_id=student_id,
            role=ActorRole.PARENT,
            permissions=scopes,
            request_id=request_id,
        )

    def require(self, permission: Permission) -> None:
        if permission not in self.permissions:
            # Imported lazily to keep this module dependency-free.
            from app.domain.errors import DomainError, ErrorCode

            raise DomainError(ErrorCode.FORBIDDEN, f"missing permission {permission.value}")


@dataclass(frozen=True, slots=True, kw_only=True)
class ParentActor:
    """A verified parent account (Step 36). Like `PlatformActor` it has no `student_id`:
    it cannot reach any student store until ParentService verifies an active link and
    builds a scoped `ActorContext.for_parent` for that one student."""

    actor_id: str
    request_id: str | None = None

    def __post_init__(self) -> None:
        if not self.actor_id or self.actor_id.startswith(SERVICE_ACTOR_PREFIX):
            raise ValueError("parent actors need a real uid")


@dataclass(frozen=True, slots=True, kw_only=True)
class PlatformActor:
    """An author, platform reviewer (Step 26) or platform admin (Step 42). Deliberately a
    different type from `ActorContext`: it has no `student_id`, so it cannot be passed to
    any student store or learning service, and authors never see student data. An admin
    reaches one student's access record only through `AccessService`.

    Authors belong to exactly one author organization (`org_id`) and see only that
    organization's packages. Reviewers and admins act for the platform and have no
    organization.
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
            raise ValueError("platform actors are authors, platform reviewers or admins")
        if (self.role is ActorRole.AUTHOR) != (self.org_id is not None):
            raise ValueError("authors belong to one organization; reviewers and admins to none")

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
