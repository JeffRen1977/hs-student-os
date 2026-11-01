from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 100


class Availability(StrEnum):
    ACTIVE = "active"
    PLANNED = "planned"


class AgentType(StrEnum):
    AP_BASE = "AP_BASE"
    DSAT = "DSAT"
    ADMISSIONS = "ADMISSIONS"


class TaskType(StrEnum):
    SOCRATIC_STUDY = "SOCRATIC_STUDY"
    FRQ_PRACTICE = "FRQ_PRACTICE"
    PRACTICE = "PRACTICE"  # course-agnostic skill practice (e.g. a choice set)
    DIAGNOSTIC = "DIAGNOSTIC"
    REINFORCEMENT = "REINFORCEMENT"


class StudyMode(StrEnum):
    GPA_SYNC = "GPA_SYNC"
    EXAM_CRUNCH = "EXAM_CRUNCH"
    ADAPTIVE = "ADAPTIVE"


@dataclass(frozen=True, slots=True, kw_only=True)
class PageRequest:
    cursor: str | None = None
    limit: int = DEFAULT_PAGE_LIMIT

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= MAX_PAGE_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_LIMIT}")


@dataclass(frozen=True, slots=True, kw_only=True)
class PaginatedResponse[T]:
    items: Sequence[T]
    next_cursor: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class IdempotencyRecord:
    """Stored result of a command, keyed by actor + route scope + key."""

    key_hash: str
    scope: str
    request_digest: str
    resource_type: str
    resource_id: str
    response_status: int
    created_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class VersionedResource:
    resource_id: str
    version: int
