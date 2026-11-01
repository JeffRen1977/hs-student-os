"""Plans (Step 25). Replanning is a command that queues a PLANNING run; GET never replans."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from app.api import presenters
from app.api.dependencies.auth import Actor, ServicesDep
from app.api.dependencies.commands import IdempotencyKeyHeader, command_key
from app.api.responses import respond
from app.api.routes.params import IdPath
from app.api.routes.sessions import schedule_dispatch
from app.schemas import common as cm
from app.schemas import plan as pl
from app.schemas import run as r

router = APIRouter(prefix="/api/plans", tags=["plans"])


@router.post("/replan", response_model=r.CommandAccepted, status_code=202)
async def replan(
    body: cm.EmptyCommand,
    request: Request,
    background: BackgroundTasks,
    actor: Actor,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.planner.request_replan(actor, cmd)
    schedule_dispatch(background, services, actor, outcome)
    return respond(
        r.CommandAccepted(run_id=outcome.value.run_id, status=outcome.value.status),
        status=202,
        replayed=outcome.replayed,
    )


@router.get("/latest", response_model=pl.Plan)
async def latest_plan(actor: Actor, services: ServicesDep) -> JSONResponse:
    return respond(presenters.plan(await services.planner.latest_plan(actor)))


@router.get("/{plan_id}", response_model=pl.Plan)
async def get_plan(plan_id: IdPath, actor: Actor, services: ServicesDep) -> JSONResponse:
    return respond(presenters.plan(await services.planner.get_plan(actor, plan_id)))
