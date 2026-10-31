"""Idempotency-Key and If-Match handling shared by command routes."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated

from fastapi import Header, Request
from pydantic import BaseModel

from app.domain.commands import CommandKey
from app.domain.errors import DomainError, ErrorCode
from app.schemas.common import IDEMPOTENCY_KEY_PATTERN, parse_if_match

_KEY = re.compile(IDEMPOTENCY_KEY_PATTERN)


def request_digest(request: Request, body: BaseModel | None) -> str:
    """Normalized request: concrete path + body with defaults filled in, keys sorted."""
    payload = {
        "path": request.url.path,
        "body": body.model_dump(mode="json", by_alias=True) if body is not None else None,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def command_key(
    request: Request, idempotency_key: str | None, body: BaseModel | None
) -> CommandKey:
    if not idempotency_key:
        raise DomainError(ErrorCode.IDEMPOTENCY_KEY_REQUIRED, "Idempotency-Key header is required.")
    if not _KEY.fullmatch(idempotency_key):
        raise DomainError(
            ErrorCode.VALIDATION_FAILED, "Idempotency-Key must be 16-128 chars [A-Za-z0-9_-]."
        )
    route = request.scope.get("route")
    template = getattr(route, "path", request.url.path)
    return CommandKey(
        scope=f"{request.method} {template}",
        key=idempotency_key,
        request_digest=request_digest(request, body),
    )


IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]
IfMatchHeader = Annotated[str | None, Header(alias="If-Match")]


def expected_version(if_match: str | None) -> int:
    if if_match is None:
        raise DomainError(ErrorCode.PRECONDITION_REQUIRED, 'If-Match: "<version>" is required.')
    try:
        return parse_if_match(if_match)
    except ValueError as exc:
        raise DomainError(ErrorCode.VALIDATION_FAILED, str(exc)) from exc
