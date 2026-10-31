"""Per-request opaque request IDs, echoed in the error envelope and `X-Request-Id`."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

REQUEST_ID_HEADER = "X-Request-Id"


def new_request_id() -> str:
    return "req_" + secrets.token_hex(8)


def get_request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else new_request_id()


def install_request_id(app: FastAPI) -> None:
    @app.middleware("http")
    async def _assign_request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Client-provided request IDs are not trusted; the server always assigns its own.
        request.state.request_id = new_request_id()
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request.state.request_id
        return response
