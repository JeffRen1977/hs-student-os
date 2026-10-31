"""Typed domain error codes (API.md). Domain code raises DomainError; the API maps it."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    # Generic
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    VERSION_CONFLICT = "VERSION_CONFLICT"
    PRECONDITION_REQUIRED = "PRECONDITION_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL = "INTERNAL"
    # Commands and idempotency
    IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    # Courses
    COURSE_NOT_AVAILABLE = "COURSE_NOT_AVAILABLE"
    COURSE_ACCESS_REQUIRED = "COURSE_ACCESS_REQUIRED"
    COURSE_NOT_ENROLLED = "COURSE_NOT_ENROLLED"
    OPEN_SESSION_EXISTS = "OPEN_SESSION_EXISTS"
    # Learning workflow
    TASK_NOT_OPEN = "TASK_NOT_OPEN"
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    RUN_IN_PROGRESS = "RUN_IN_PROGRESS"
    RUN_TERMINAL = "RUN_TERMINAL"
    COMPLETION_REQUIREMENTS_NOT_MET = "COMPLETION_REQUIREMENTS_NOT_MET"
    FILE_NOT_READY = "FILE_NOT_READY"
    # Events
    EVENT_CURSOR_EXPIRED = "EVENT_CURSOR_EXPIRED"
    # Legacy endpoints
    API_CONTRACT_REPLACED = "API_CONTRACT_REPLACED"


class DomainError(Exception):
    def __init__(self, code: ErrorCode, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
