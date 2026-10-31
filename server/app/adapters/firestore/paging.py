"""Opaque keyset cursors for paginated collection reads."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from app.adapters.firestore.documents import Doc, DocTxn, Filter, QuerySpec
from app.domain.errors import DomainError, ErrorCode
from app.domain.types.common import PageRequest, PaginatedResponse

_DT = "$dt"


def _encode_value(value: Any) -> Any:
    return {_DT: value.isoformat()} if isinstance(value, datetime) else value


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {_DT}:
        return datetime.fromisoformat(value[_DT])
    return value


def encode_cursor(values: Sequence[Any]) -> str:
    raw = json.dumps([_encode_value(v) for v in values], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, width: int) -> list[Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        values = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "invalid cursor") from exc
    if not isinstance(values, list) or len(values) != width:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "invalid cursor")
    return [_decode_value(v) for v in values]


async def paged_query[T](
    txn: DocTxn,
    collection: str,
    *,
    filters: Sequence[Filter],
    order_by: Sequence[str],
    page: PageRequest,
    decode: Callable[[Doc], T],
) -> PaginatedResponse[T]:
    start_after = decode_cursor(page.cursor, len(order_by)) if page.cursor else None
    docs = await txn.query(
        collection,
        QuerySpec(
            filters=filters, order_by=order_by, start_after=start_after, limit=page.limit + 1
        ),
    )
    has_more = len(docs) > page.limit
    docs = docs[: page.limit]
    next_cursor = encode_cursor([docs[-1][f] for f in order_by]) if has_more and docs else None
    return PaginatedResponse(items=[decode(d) for d in docs], next_cursor=next_cursor)
