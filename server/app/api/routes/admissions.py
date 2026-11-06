"""Admissions workspace (Step 35, API.md §6.5). Requires `entitlements.admissions`."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Path, Request
from fastapi.responses import JSONResponse

from app.api.dependencies.auth import Actor, ServicesDep
from app.api.dependencies.commands import (
    IdempotencyKeyHeader,
    IfMatchHeader,
    command_key,
    expected_version,
)
from app.api.responses import respond
from app.api.routes.sessions import schedule_dispatch
from app.domain.admissions_service import ActivityInput, DeadlineInput
from app.domain.types.admissions import (
    Activity,
    Deadline,
    DeadlineVerification,
    Essay,
    Fact,
    FeedbackKind,
    FeedbackRequest,
    InterviewAnswer,
)
from app.domain.types.run import Run
from app.schemas import admissions as ad
from app.schemas.common import EmptyCommand

router = APIRouter(prefix="/api/admissions", tags=["admissions"])
IdPath = Annotated[str, Path(pattern=r"^[A-Za-z0-9_\-]{1,64}$")]

UNCERTAINTY = {
    DeadlineVerification.VERIFIED: "Checked against the source recently.",
    DeadlineVerification.STALE: "Checked over 30 days ago: re-check the school's page.",
    DeadlineVerification.UNVERIFIED: "Not yet checked against the source: verify it.",
    DeadlineVerification.UNSOURCED: "No source: add the school's official page before relying on "
    "it.",
}


def _queued(run: Run) -> ad.QueuedView:
    return ad.QueuedView(run_id=run.run_id, status=run.status)


def answer_view(a: InterviewAnswer) -> ad.InterviewAnswerView:
    return ad.InterviewAnswerView(
        answer_id=a.answer_id, prompt_id=a.prompt_id, prompt_set_version=a.prompt_set_version,
        text=a.text, run_id=a.run_id, created_at=a.created_at,
    )  # fmt: skip


def fact_view(f: Fact) -> ad.FactView:
    return ad.FactView(
        fact_id=f.fact_id, text=f.text, category=f.category,  # type: ignore[arg-type]
        status=f.status.value, source=f.source.value, answer_id=f.answer_id,
        quote=f.quote, created_at=f.created_at, decided_at=f.decided_at, version=f.version,
    )  # fmt: skip


def activity_view(a: Activity) -> ad.ActivityView:
    return ad.ActivityView(
        activity_id=a.activity_id, name=a.name, role=a.role, description=a.description,
        hours_per_week=a.hours_per_week, weeks_per_year=a.weeks_per_year,
        fact_ids=list(a.fact_ids), confirmed_at=a.confirmed_at, updated_at=a.updated_at,
        version=a.version,
    )  # fmt: skip


def deadline_view(d: Deadline, today: date) -> ad.DeadlineView:
    v = d.verification(today)
    return ad.DeadlineView(
        deadline_id=d.deadline_id, school=d.school, kind=d.kind, due_date=d.due_date,
        days_left=(d.due_date - today).days, source_url=d.source_url,
        source_checked_on=d.source_checked_on, verification=v.value,
        uncertainty=UNCERTAINTY[v], notes=d.notes, version=d.version,
    )  # fmt: skip


def essay_view(e: Essay) -> ad.EssayView:
    return ad.EssayView(
        essay_id=e.essay_id, title=e.title, prompt=e.prompt, draft=e.draft,
        version=e.version, active_run_id=e.active_run_id, updated_at=e.updated_at,
    )  # fmt: skip


def feedback_view(f: FeedbackRequest) -> ad.FeedbackView:
    return ad.FeedbackView(
        feedback_id=f.feedback_id, essay_id=f.essay_id, essay_version=f.essay_version,
        kind=f.kind.value, run_id=f.run_id,
        items=[
            ad.FeedbackItemView(type=i.type.value, text=i.text, fact_ids=list(i.fact_ids))
            for i in f.items
        ],
        created_at=f.created_at, completed_at=f.completed_at,
    )  # fmt: skip


# ---- Interview and facts (35.1) -----------------------------------------------------------


@router.get("/interview/prompts", response_model=ad.InterviewPromptList)
async def interview_prompts(actor: Actor, services: ServicesDep) -> JSONResponse:
    await services.admissions.list_answers(actor)  # access check
    ps = services.admissions.prompts()
    return respond(
        ad.InterviewPromptList(
            prompt_set_version=ps.version,
            prompts=[
                ad.InterviewPromptView(prompt_id=p.prompt_id, category=p.category, text=p.text)  # type: ignore[arg-type]
                for p in ps.prompts
            ],
        )
    )


@router.post("/interview/answers", response_model=ad.InterviewAnswerAccepted, status_code=202)
async def answer_interview(
    body: ad.InterviewAnswerRequest, request: Request, background: BackgroundTasks,
    actor: Actor, services: ServicesDep, idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:  # fmt: skip
    cmd = command_key(request, idempotency_key, body)
    out = await services.admissions.answer(actor, body.prompt_id, body.text, cmd)
    schedule_dispatch(background, services, actor, out)
    view = ad.InterviewAnswerAccepted(
        **answer_view(out.value.value).model_dump(), run=_queued(out.value.run)
    )
    return respond(view, status=202, replayed=out.replayed)


@router.get("/interview/answers", response_model=ad.InterviewAnswerList)
async def list_answers(actor: Actor, services: ServicesDep) -> JSONResponse:
    answers = await services.admissions.list_answers(actor)
    return respond(ad.InterviewAnswerList(answers=[answer_view(a) for a in answers]))


@router.get("/facts", response_model=ad.FactList)
async def list_facts(actor: Actor, services: ServicesDep) -> JSONResponse:
    facts = await services.admissions.list_facts(actor)
    return respond(ad.FactList(facts=[fact_view(f) for f in facts]))


@router.post("/facts", response_model=ad.FactView, status_code=201)
async def add_fact(
    body: ad.AddFactRequest, request: Request, actor: Actor, services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:  # fmt: skip
    cmd = command_key(request, idempotency_key, body)
    out = await services.admissions.add_fact(actor, body.text, body.category, cmd)
    return respond(fact_view(out.value), status=201, replayed=out.replayed)


@router.post("/facts/{fact_id}/confirm", response_model=ad.FactView)
async def confirm_fact(
    fact_id: IdPath, body: ad.ConfirmFactRequest, request: Request, actor: Actor,
    services: ServicesDep, idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:  # fmt: skip
    cmd = command_key(request, idempotency_key, body)
    out = await services.admissions.decide_fact(actor, fact_id, True, cmd, text=body.text)
    return respond(fact_view(out.value), replayed=out.replayed)


@router.post("/facts/{fact_id}/reject", response_model=ad.FactView)
async def reject_fact(
    fact_id: IdPath, body: EmptyCommand, request: Request, actor: Actor,
    services: ServicesDep, idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:  # fmt: skip
    cmd = command_key(request, idempotency_key, body)
    out = await services.admissions.decide_fact(actor, fact_id, False, cmd)
    return respond(fact_view(out.value), replayed=out.replayed)


# ---- Activities (35.4) --------------------------------------------------------------------


def _activity_input(body: ad.ActivityRequest) -> ActivityInput:
    return ActivityInput(
        name=body.name, role=body.role, description=body.description,
        hours_per_week=body.hours_per_week, weeks_per_year=body.weeks_per_year,
        fact_ids=tuple(body.fact_ids), student_confirmed=body.student_confirmed,
    )  # fmt: skip


@router.get("/activities", response_model=ad.ActivityList)
async def list_activities(actor: Actor, services: ServicesDep) -> JSONResponse:
    items = await services.admissions.list_activities(actor)
    return respond(ad.ActivityList(activities=[activity_view(a) for a in items]))


@router.post("/activities", response_model=ad.ActivityView, status_code=201)
async def create_activity(
    body: ad.ActivityRequest, request: Request, actor: Actor, services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:  # fmt: skip
    cmd = command_key(request, idempotency_key, body)
    out = await services.admissions.create_activity(actor, _activity_input(body), cmd)
    return respond(activity_view(out.value), status=201, etag=out.value.version,
                   replayed=out.replayed)  # fmt: skip


@router.patch("/activities/{activity_id}", response_model=ad.ActivityView)
async def update_activity(
    activity_id: IdPath, body: ad.ActivityRequest, actor: Actor, services: ServicesDep,
    if_match: IfMatchHeader = None,
) -> JSONResponse:  # fmt: skip
    version = expected_version(if_match)
    a = await services.admissions.update_activity(
        actor, activity_id, _activity_input(body), version
    )
    return respond(activity_view(a), etag=a.version)


# ---- Deadlines (35.2) ---------------------------------------------------------------------


def _deadline_input(body: ad.DeadlineRequest) -> DeadlineInput:
    return DeadlineInput(
        school=body.school, kind=body.kind, due_date=body.due_date, source_url=body.source_url,
        source_checked_on=body.source_checked_on, notes=body.notes,
    )  # fmt: skip


@router.get("/deadlines", response_model=ad.DeadlineList)
async def list_deadlines(actor: Actor, services: ServicesDep) -> JSONResponse:
    items = await services.admissions.list_deadlines(actor)
    today = await services.admissions.today(actor)
    return respond(ad.DeadlineList(deadlines=[deadline_view(d, today) for d in items]))


@router.post("/deadlines", response_model=ad.DeadlineView, status_code=201)
async def create_deadline(
    body: ad.DeadlineRequest, request: Request, actor: Actor, services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:  # fmt: skip
    cmd = command_key(request, idempotency_key, body)
    out = await services.admissions.create_deadline(actor, _deadline_input(body), cmd)
    today = await services.admissions.today(actor)
    return respond(deadline_view(out.value, today), status=201, etag=out.value.version,
                   replayed=out.replayed)  # fmt: skip


@router.patch("/deadlines/{deadline_id}", response_model=ad.DeadlineView)
async def update_deadline(
    deadline_id: IdPath, body: ad.DeadlineRequest, actor: Actor, services: ServicesDep,
    if_match: IfMatchHeader = None,
) -> JSONResponse:  # fmt: skip
    version = expected_version(if_match)
    d = await services.admissions.update_deadline(
        actor, deadline_id, _deadline_input(body), version
    )
    return respond(deadline_view(d, await services.admissions.today(actor)), etag=d.version)


# ---- Essays (35.3) ------------------------------------------------------------------------


@router.get("/essays", response_model=ad.EssayList)
async def list_essays(actor: Actor, services: ServicesDep) -> JSONResponse:
    items = await services.admissions.list_essays(actor)
    return respond(ad.EssayList(essays=[essay_view(e) for e in items]))


@router.post("/essays", response_model=ad.EssayView, status_code=201)
async def create_essay(
    body: ad.CreateEssayRequest, request: Request, actor: Actor, services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:  # fmt: skip
    cmd = command_key(request, idempotency_key, body)
    out = await services.admissions.create_essay(actor, body.title, body.prompt, cmd)
    return respond(essay_view(out.value), status=201, etag=out.value.version,
                   replayed=out.replayed)  # fmt: skip


@router.get("/essays/{essay_id}", response_model=ad.EssayView)
async def get_essay(essay_id: IdPath, actor: Actor, services: ServicesDep) -> JSONResponse:
    e = await services.admissions.get_essay(actor, essay_id)
    return respond(essay_view(e), etag=e.version)


@router.patch("/essays/{essay_id}", response_model=ad.EssayView)
async def save_draft(
    essay_id: IdPath, body: ad.SaveDraftRequest, actor: Actor, services: ServicesDep,
    if_match: IfMatchHeader = None,
) -> JSONResponse:  # fmt: skip
    version = expected_version(if_match)
    e = await services.admissions.save_draft(actor, essay_id, body.draft, version)
    return respond(essay_view(e), etag=e.version)


@router.post("/essays/{essay_id}/feedback", response_model=ad.FeedbackAccepted, status_code=202)
async def request_feedback(
    essay_id: IdPath, body: ad.FeedbackRequestBody, request: Request,
    background: BackgroundTasks, actor: Actor, services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:  # fmt: skip
    cmd = command_key(request, idempotency_key, body)
    out = await services.admissions.request_feedback(actor, essay_id, FeedbackKind(body.kind), cmd)
    schedule_dispatch(background, services, actor, out)
    view = ad.FeedbackAccepted(
        **feedback_view(out.value.value).model_dump(), run=_queued(out.value.run)
    )
    return respond(view, status=202, replayed=out.replayed)


@router.get("/essays/{essay_id}/feedback", response_model=ad.FeedbackList)
async def list_feedback(essay_id: IdPath, actor: Actor, services: ServicesDep) -> JSONResponse:
    items = await services.admissions.list_feedback(actor, essay_id)
    return respond(ad.FeedbackList(feedback=[feedback_view(f) for f in items]))
