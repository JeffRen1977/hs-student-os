"""Worker service HTTP surface (Cloud Run "worker" service; Step 15.3).

Cloud Tasks POSTs deliveries here with an OIDC token. A 2xx acknowledges the task; a 503
asks Cloud Tasks to retry later (live lease held elsewhere, or a retryable failure).
Cloud Scheduler drives the outbox and recovery scans through the same authenticated
surface. These routes are never mounted on the student-facing API.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from app.api.errors import install_error_handlers
from app.api.request_id import install_request_id
from app.bootstrap import Services, get_services
from app.config import APP_VERSION, Settings, get_settings
from app.domain.errors import DomainError, ErrorCode
from app.domain.run_execution import ProcessResult
from app.domain.types.outbox import Delivery
from app.schemas.common import ApiModel, OpaqueId, RequestModel


class DeliveryRequest(RequestModel):
    delivery_id: OpaqueId
    student_id: OpaqueId
    run_id: OpaqueId


class DeliveryResponse(ApiModel):
    result: Literal["done", "retry"]


class ScanResponse(ApiModel):
    count: int = Field(ge=0)


async def require_service(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise DomainError(ErrorCode.UNAUTHENTICATED, "Service authentication required.")
    services = get_services(request)
    return await services.service_authenticator.authenticate(authorization[7:].strip())


router = APIRouter(prefix="/internal", dependencies=[Depends(require_service)])


@router.post("/runs/execute", response_model=DeliveryResponse)
async def execute_run(body: DeliveryRequest, request: Request) -> JSONResponse:
    services = get_services(request)
    result = await services.run_execution.process(
        Delivery(delivery_id=body.delivery_id, student_id=body.student_id, run_id=body.run_id)
    )
    status = 503 if result is ProcessResult.RETRY else 200
    return JSONResponse(status_code=status, content={"result": result.value})


@router.post("/outbox/dispatch", response_model=ScanResponse)
async def dispatch_outbox(request: Request) -> ScanResponse:
    return ScanResponse(count=await get_services(request).dispatcher.dispatch_pending())


@router.post("/runs/recover", response_model=ScanResponse)
async def recover_runs(request: Request) -> ScanResponse:
    return ScanResponse(count=await get_services(request).recovery.requeue_stalled())


def create_worker_app(
    settings: Settings | None = None, services: Services | None = None
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="High School Student OS Worker",
        version=APP_VERSION,
        docs_url=None,
        openapi_url=None,
        redoc_url=None,
    )
    app.state.settings = settings
    if services is not None:
        app.state.services = services
    install_request_id(app)
    install_error_handlers(app)
    app.include_router(router)
    return app
