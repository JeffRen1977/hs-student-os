from __future__ import annotations

from collections.abc import Mapping

from app.domain.errors import DomainError, ErrorCode
from app.schemas.common import ApiModel

ERROR_STATUS: Mapping[ErrorCode, int] = {
    ErrorCode.VALIDATION_FAILED: 400,
    ErrorCode.IDEMPOTENCY_KEY_REQUIRED: 400,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.COURSE_ACCESS_REQUIRED: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.VERSION_CONFLICT: 409,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.COURSE_NOT_AVAILABLE: 409,
    ErrorCode.COURSE_NOT_ENROLLED: 409,
    ErrorCode.OPEN_SESSION_EXISTS: 409,
    ErrorCode.TASK_NOT_OPEN: 409,
    ErrorCode.INVALID_STATE_TRANSITION: 409,
    ErrorCode.RUN_IN_PROGRESS: 409,
    ErrorCode.RUN_TERMINAL: 409,
    ErrorCode.COMPLETION_REQUIREMENTS_NOT_MET: 409,
    ErrorCode.FILE_NOT_READY: 409,
    ErrorCode.API_CONTRACT_REPLACED: 410,
    ErrorCode.EVENT_CURSOR_EXPIRED: 410,
    ErrorCode.PRECONDITION_REQUIRED: 428,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.BUDGET_EXCEEDED: 429,
    ErrorCode.INTERNAL: 500,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
}


class ErrorBody(ApiModel):
    code: ErrorCode
    message: str
    request_id: str
    retryable: bool


class ErrorEnvelope(ApiModel):
    error: ErrorBody


__all__ = ["ERROR_STATUS", "DomainError", "ErrorBody", "ErrorCode", "ErrorEnvelope"]
