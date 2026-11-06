"""Authentication dependency: verified Firebase ID token → ActorContext (Step 8).

Identity comes only from the verified token. Caller-asserted identity (an `X-User-Email`
header from the v0.1 API, or a `studentId` query parameter) is rejected outright rather
than ignored, so a stale client fails loudly instead of silently acting as someone else.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.api.request_id import get_request_id
from app.bootstrap import Services, get_services
from app.domain.errors import DomainError, ErrorCode
from app.domain.types.actor import (
    SERVICE_ACTOR_PREFIX,
    ActorContext,
    ActorRole,
    ParentActor,
    PlatformActor,
)

FORBIDDEN_IDENTITY_HEADERS = ("x-user-email", "x-student-id", "x-user-id")
FORBIDDEN_IDENTITY_PARAMS = ("studentId", "student_id", "email")


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization")
    if not header:
        raise DomainError(ErrorCode.UNAUTHENTICATED, "Sign in required.")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip() or " " in token.strip():
        raise DomainError(ErrorCode.UNAUTHENTICATED, "Malformed Authorization header.")
    return token.strip()


def _reject_asserted_identity(request: Request) -> None:
    for name in FORBIDDEN_IDENTITY_HEADERS:
        if name in request.headers:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                f"{name} is not accepted; identity comes from the ID token.",
            )
    for name in FORBIDDEN_IDENTITY_PARAMS:
        if name in request.query_params:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED,
                f"{name} is not accepted; identity comes from the ID token.",
            )


async def get_actor(
    request: Request, services: Annotated[Services, Depends(get_services)]
) -> ActorContext:
    _reject_asserted_identity(request)
    identity = await services.token_verifier.verify(_bearer_token(request))
    if identity.uid.startswith(SERVICE_ACTOR_PREFIX):
        raise DomainError(ErrorCode.UNAUTHENTICATED, "Invalid subject.")
    await services.content_sync.ensure_fresh()
    student_id = await services.identities.resolve(identity.uid)
    if student_id is None:
        raise DomainError(ErrorCode.FORBIDDEN, "This account has no student record.")
    request.state.token_expires_at = identity.expires_at  # long-lived streams stop here
    return ActorContext.for_student(student_id, request_id=get_request_id(request))


async def get_platform_actor(
    request: Request, services: Annotated[Services, Depends(get_services)]
) -> PlatformActor:
    """Authors and platform reviewers (Step 26). A student account is not a platform
    member, so it gets 403 on every authoring and review route."""
    _reject_asserted_identity(request)
    identity = await services.token_verifier.verify(_bearer_token(request))
    if identity.uid.startswith(SERVICE_ACTOR_PREFIX):
        raise DomainError(ErrorCode.UNAUTHENTICATED, "Invalid subject.")
    member = await services.platform_members.resolve(identity.uid)
    if member is None:
        raise DomainError(ErrorCode.FORBIDDEN, "This account is not a course author or reviewer.")
    return PlatformActor.for_member(
        member.uid, ActorRole(member.role), member.org_id, request_id=get_request_id(request)
    )


async def get_parent_actor(
    request: Request, services: Annotated[Services, Depends(get_services)]
) -> tuple[ParentActor, str]:
    """Parents (Step 36): a provisioned `parents/{uid}` account, never a student. Returns
    the actor and the parent's display name. Students and platform members get 403."""
    _reject_asserted_identity(request)
    identity = await services.token_verifier.verify(_bearer_token(request))
    if identity.uid.startswith(SERVICE_ACTOR_PREFIX):
        raise DomainError(ErrorCode.UNAUTHENTICATED, "Invalid subject.")
    name = await services.parent_directory.resolve(identity.uid)
    if name is None:
        raise DomainError(ErrorCode.FORBIDDEN, "This account is not a parent account.")
    return ParentActor(actor_id=identity.uid, request_id=get_request_id(request)), name


Actor = Annotated[ActorContext, Depends(get_actor)]
ParentDep = Annotated[tuple[ParentActor, str], Depends(get_parent_actor)]
Platform = Annotated[PlatformActor, Depends(get_platform_actor)]
ServicesDep = Annotated[Services, Depends(get_services)]
