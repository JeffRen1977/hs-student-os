"""Run status, typed input, and cancellation (Step 14)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from app.api import presenters
from app.api.dependencies.auth import Actor, ServicesDep
from app.api.dependencies.commands import IdempotencyKeyHeader, command_key
from app.api.responses import respond
from app.api.routes.params import IdPath
from app.api.routes.sessions import schedule_dispatch
from app.domain.types.run import RunStatus
from app.schemas import common as cm
from app.schemas import run as r

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.get("/{run_id}", response_model=r.Run)
async def get_run(run_id: IdPath, actor: Actor, services: ServicesDep) -> JSONResponse:
    return respond(presenters.run(await services.commands.get_run(actor, run_id)))


@router.post("/{run_id}/input", response_model=r.CommandAccepted, status_code=202)
async def provide_input(
    run_id: IdPath,
    body: r.RunInputRequest,
    request: Request,
    background: BackgroundTasks,
    actor: Actor,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.commands.provide_input(
        actor,
        run_id,
        input_request_id=body.input_request_id,
        confirmed_text=body.value.confirmed_text,
        cmd=cmd,
    )
    schedule_dispatch(background, services, actor, outcome)
    return respond(
        r.CommandAccepted(run_id=outcome.value.run_id, status=outcome.value.status),
        status=202,
        replayed=outcome.replayed,
    )


@router.post("/{run_id}/cancel", response_model=r.CommandAccepted, status_code=202)
async def cancel_run(
    run_id: IdPath,
    body: cm.EmptyCommand,
    request: Request,
    actor: Actor,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.commands.cancel_run(actor, run_id, cmd)
    already_cancelled = (
        not outcome.created and not outcome.replayed and outcome.value.status is RunStatus.CANCELLED
    )
    return respond(
        r.CommandAccepted(run_id=outcome.value.run_id, status=outcome.value.status),
        status=200 if already_cancelled else 202,
        replayed=outcome.replayed,
    )
