"""Translate exceptions into the standard error envelope (API.md §0)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.api.request_id import get_request_id
from app.schemas.error import ERROR_STATUS, DomainError, ErrorBody, ErrorCode, ErrorEnvelope

logger = logging.getLogger(__name__)

_STATUS_FALLBACK_CODE: dict[int, ErrorCode] = {
    400: ErrorCode.VALIDATION_FAILED,
    401: ErrorCode.UNAUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.VERSION_CONFLICT,
    428: ErrorCode.PRECONDITION_REQUIRED,
    429: ErrorCode.RATE_LIMITED,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}


def _envelope(
    request: Request,
    status: int,
    code: ErrorCode,
    message: str,
    retryable: bool,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorEnvelope(
        error=ErrorBody(
            code=code,
            message=message,
            request_id=get_request_id(request),
            retryable=retryable,
        )
    )
    return JSONResponse(status_code=status, content=body.model_dump(by_alias=True), headers=headers)


async def _domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return _envelope(request, ERROR_STATUS[exc.code], exc.code, exc.message, exc.retryable)


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Only field locations and error types are returned; submitted values are never echoed
    # back because they may contain student answers.
    fields = sorted({".".join(str(p) for p in err.get("loc", ())) for err in exc.errors()})
    message = "Request validation failed: " + ", ".join(fields) if fields else "Invalid request"
    return _envelope(request, 400, ErrorCode.VALIDATION_FAILED, message, retryable=False)


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    code = _STATUS_FALLBACK_CODE.get(exc.status_code, ErrorCode.INTERNAL)
    message = exc.detail if isinstance(exc.detail, str) else code.value
    headers: dict[str, Any] | None = getattr(exc, "headers", None)
    return _envelope(request, exc.status_code, code, message, retryable=False, headers=headers)


async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled_error", extra={"requestId": get_request_id(request), "error": type(exc).__name__}
    )
    return _envelope(request, 500, ErrorCode.INTERNAL, "Internal server error", retryable=True)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(HTTPException, _http_exception_handler)
    app.add_exception_handler(Exception, _unhandled_handler)
