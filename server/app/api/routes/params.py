from __future__ import annotations

from typing import Annotated

from fastapi import Path, Query

from app.domain.types.common import DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT, PageRequest

ID_PATTERN = r"^[A-Za-z0-9_\-:.]+$"
COURSE_PATTERN = r"^[a-z][a-z0-9_]{1,31}$"

IdPath = Annotated[str, Path(min_length=1, max_length=128, pattern=ID_PATTERN)]
CoursePath = Annotated[str, Path(pattern=COURSE_PATTERN)]
Cursor = Annotated[str | None, Query(max_length=512)]
Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)]


def page(cursor: str | None, limit: int = DEFAULT_PAGE_LIMIT) -> PageRequest:
    return PageRequest(cursor=cursor, limit=limit)
