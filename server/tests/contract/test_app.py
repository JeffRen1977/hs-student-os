from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.domain.errors import DomainError, ErrorCode
from app.main import create_app
from app.schemas.error import ErrorEnvelope
from app.schemas.session import CreateSessionRequest


@pytest.fixture
def app(clean_env: pytest.MonkeyPatch) -> FastAPI:
    app = create_app(Settings(_env_file=None))  # type: ignore[call-arg]

    # Probe routes exercising the error handlers; not part of the public API.
    @app.post("/_probe/validation")
    async def _validation(body: CreateSessionRequest) -> dict[str, str]:
        return {"taskId": body.task_id}

    @app.get("/_probe/domain-error")
    async def _domain_error() -> None:
        raise DomainError(ErrorCode.RUN_IN_PROGRESS, "A run is already active in this session.")

    @app.get("/_probe/crash")
    async def _crash() -> None:
        raise RuntimeError("secret internal detail")

    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncClient:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}
    assert response.headers["X-Request-Id"].startswith("req_")


async def test_unknown_route_uses_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/nope")
    assert response.status_code == 404
    body = ErrorEnvelope.model_validate(response.json())
    assert body.error.code is ErrorCode.NOT_FOUND
    assert body.error.request_id == response.headers["X-Request-Id"]


async def test_validation_error_envelope_does_not_echo_input(client: AsyncClient) -> None:
    response = await client.post(
        "/_probe/validation", json={"taskId": "t1", "scoreDelta": "my secret answer text"}
    )
    assert response.status_code == 400
    body = ErrorEnvelope.model_validate(response.json())
    assert body.error.code is ErrorCode.VALIDATION_FAILED
    assert "scoreDelta" in body.error.message
    assert "my secret answer text" not in response.text


async def test_domain_error_maps_to_typed_status(client: AsyncClient) -> None:
    response = await client.get("/_probe/domain-error")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUN_IN_PROGRESS"
    assert response.json()["error"]["retryable"] is False


async def test_unhandled_error_is_generic(client: AsyncClient) -> None:
    response = await client.get("/_probe/crash")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL"
    assert "secret internal detail" not in response.text


async def test_client_request_id_is_not_trusted(client: AsyncClient) -> None:
    response = await client.get("/api/health", headers={"X-Request-Id": "req_spoofed"})
    assert response.headers["X-Request-Id"] != "req_spoofed"


def test_no_public_event_publication_route(app: FastAPI) -> None:
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if path.startswith("/api/") and "events" in path:
            assert methods <= {"GET", "HEAD"}, f"{path} must not accept writes"
