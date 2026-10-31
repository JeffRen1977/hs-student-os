from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)
from pydantic.alias_generators import to_camel

from app.domain.types.common import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT


class ApiModel(BaseModel):
    """Base for every contract model: camelCase JSON, unknown fields rejected."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        str_strip_whitespace=False,
        validate_default=True,
    )


class RequestModel(ApiModel):
    """Client → server bodies. Immutable once parsed."""

    model_config = ConfigDict(frozen=True)


# ---- Identifiers -------------------------------------------------------------------------

OpaqueId = Annotated[
    str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_\-:.]+$")
]
CourseId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,31}$")]
SkillId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*(\.[a-z0-9][a-z0-9\-]*)+$")]
SemVer = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]

IDEMPOTENCY_KEY_PATTERN = r"^[A-Za-z0-9_\-]{16,128}$"
IdempotencyKey = Annotated[str, StringConstraints(pattern=IDEMPOTENCY_KEY_PATTERN)]


# ---- Time --------------------------------------------------------------------------------


def _require_utc(value: datetime) -> datetime:
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamps must be UTC (Z)")
    return value.astimezone(UTC)


UtcDatetime = Annotated[AwareDatetime, AfterValidator(_require_utc)]
LocalDate = date

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
LocalTime = Annotated[str, StringConstraints(pattern=_HHMM.pattern)]


def _require_iana_timezone(value: str) -> str:
    # Reject bare abbreviations/offsets ("PST", "UTC+8"): plans need DST-aware zones.
    if value not in available_timezones() or ("/" not in value and value != "UTC"):
        raise ValueError("must be an IANA timezone such as America/Los_Angeles")
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:  # pragma: no cover - guarded above
        raise ValueError("unknown timezone") from exc
    return value


IanaTimezone = Annotated[str, AfterValidator(_require_iana_timezone)]


# ---- Concurrency -------------------------------------------------------------------------

_ETAG = re.compile(r'^"(\d{1,18})"$')


def parse_if_match(header: str) -> int:
    """Parse `If-Match: "<version>"` into a version number (API.md §0)."""
    match = _ETAG.fullmatch(header.strip())
    if not match:
        raise ValueError('If-Match must look like "<version>"')
    return int(match.group(1))


def format_etag(version: int) -> str:
    return f'"{version}"'


# ---- Pagination --------------------------------------------------------------------------


class PageQuery(ApiModel):
    cursor: Annotated[str, StringConstraints(max_length=512)] | None = None
    limit: int = Field(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT)


class EmptyCommand(RequestModel):
    """`{}` bodies for cancel/complete/abandon. Any field is rejected."""
