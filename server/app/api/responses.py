from __future__ import annotations

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.schemas.common import format_etag

REPLAYED_HEADER = "Idempotency-Replayed"


def respond(
    model: BaseModel, *, status: int = 200, etag: int | None = None, replayed: bool = False
) -> JSONResponse:
    headers: dict[str, str] = {}
    if etag is not None:
        headers["ETag"] = format_etag(etag)
    if replayed:
        headers[REPLAYED_HEADER] = "true"
    return JSONResponse(
        status_code=status,
        content=model.model_dump(mode="json", by_alias=True),
        headers=headers,
    )
