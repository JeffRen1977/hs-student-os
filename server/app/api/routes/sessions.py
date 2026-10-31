"""Sessions, their conversation, and the commands that start agent work (Steps 13–14)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import JSONResponse

from app.api import presenters
from app.api.dependencies.auth import Actor, ServicesDep
from app.api.dependencies.commands import IdempotencyKeyHeader, command_key
from app.api.responses import respond
from app.api.routes.params import COURSE_PATTERN, ID_PATTERN, Cursor, IdPath, Limit, page
from app.bootstrap import Services
from app.domain.commands import Outcome
from app.domain.ports.repositories import SessionQuery
from app.domain.types.actor import ActorContext
from app.domain.types.common import DEFAULT_PAGE_LIMIT
from app.domain.types.submission import SubmissionAnswer, SubmissionInput
from app.schemas import common as cm
from app.schemas import message as m
from app.schemas import session as s
from app.schemas import submission as sb

router = APIRouter(prefix="/api", tags=["sessions"])


def schedule_dispatch(
    background: BackgroundTasks, services: Services, actor: ActorContext, outcome: Outcome[object]
) -> None:
    """After the transaction commits, try to hand the run to the queue right away."""
    if outcome.delivery_id and not outcome.replayed:
        background.add_task(
            services.dispatcher.dispatch_after_commit, actor.student_id, outcome.delivery_id
        )


@router.post("/sessions", response_model=s.Session, status_code=201)
async def create_session(
    body: s.CreateSessionRequest,
    request: Request,
    actor: Actor,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.sessions.create_session(actor, body.task_id, cmd)
    return respond(
        presenters.session(outcome.value),
        status=201 if outcome.created else 200,
        replayed=outcome.replayed,
    )


@router.get("/sessions", response_model=s.SessionList)
async def list_sessions(
    actor: Actor,
    services: ServicesDep,
    task_id: Annotated[
        str | None, Query(alias="taskId", pattern=ID_PATTERN, max_length=128)
    ] = None,
    course_id: Annotated[str | None, Query(alias="courseId", pattern=COURSE_PATTERN)] = None,
    cursor: Cursor = None,
    limit: Limit = DEFAULT_PAGE_LIMIT,
) -> JSONResponse:
    result = await services.sessions.list_sessions(
        actor, SessionQuery(task_id=task_id, course_id=course_id), page(cursor, limit)
    )
    return respond(
        s.SessionList(
            sessions=[presenters.session(x) for x in result.items], next_cursor=result.next_cursor
        )
    )


@router.get("/sessions/{session_id}", response_model=s.Session)
async def get_session(session_id: IdPath, actor: Actor, services: ServicesDep) -> JSONResponse:
    return respond(presenters.session(await services.sessions.get_session(actor, session_id)))


@router.post("/sessions/{session_id}/abandon", response_model=s.Session)
async def abandon_session(
    session_id: IdPath,
    body: cm.EmptyCommand,
    request: Request,
    actor: Actor,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.sessions.abandon_session(actor, session_id, cmd)
    return respond(presenters.session(outcome.value), replayed=outcome.replayed)


@router.get("/sessions/{session_id}/messages", response_model=m.MessageList)
async def list_messages(
    session_id: IdPath,
    actor: Actor,
    services: ServicesDep,
    cursor: Cursor = None,
    limit: Limit = DEFAULT_PAGE_LIMIT,
) -> JSONResponse:
    result = await services.sessions.list_messages(actor, session_id, page(cursor, limit))
    return respond(
        m.MessageList(
            messages=[presenters.message(x) for x in result.items], next_cursor=result.next_cursor
        )
    )


@router.get("/sessions/{session_id}/submissions", response_model=sb.SubmissionList)
async def list_submissions(
    session_id: IdPath,
    actor: Actor,
    services: ServicesDep,
    cursor: Cursor = None,
    limit: Limit = DEFAULT_PAGE_LIMIT,
) -> JSONResponse:
    result = await services.sessions.list_submissions(actor, session_id, page(cursor, limit))
    return respond(
        sb.SubmissionList(
            submissions=[presenters.submission(x) for x in result.items],
            next_cursor=result.next_cursor,
        )
    )


@router.post(
    "/sessions/{session_id}/submissions", response_model=sb.SubmissionAccepted, status_code=202
)
async def submit_answer(
    session_id: IdPath,
    body: sb.CreateSubmissionRequest,
    request: Request,
    background: BackgroundTasks,
    actor: Actor,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.commands.submit_answer(
        actor,
        session_id,
        SubmissionInput(
            question_id=body.question_id,
            question_version=body.question_version,
            answer=SubmissionAnswer(text=body.answer.text, file_ids=tuple(body.answer.file_ids)),
            supersedes_submission_id=body.supersedes_submission_id,
        ),
        cmd,
    )
    schedule_dispatch(background, services, actor, outcome)
    accepted = outcome.value
    return respond(
        sb.SubmissionAccepted(
            submission_id=accepted.submission.submission_id,
            run_id=accepted.run.run_id,
            status=accepted.run.status,
        ),
        status=202,
        replayed=outcome.replayed,
    )


@router.post("/sessions/{session_id}/messages", response_model=sb.MessageAccepted, status_code=202)
async def send_message(
    session_id: IdPath,
    body: sb.CreateMessageRequest,
    request: Request,
    background: BackgroundTasks,
    actor: Actor,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.commands.send_message(
        actor, session_id, text=body.text, file_ids=body.file_ids, cmd=cmd
    )
    schedule_dispatch(background, services, actor, outcome)
    accepted = outcome.value
    return respond(
        sb.MessageAccepted(
            message_id=accepted.message.message_id,
            run_id=accepted.run.run_id,
            status=accepted.run.status,
        ),
        status=202,
        replayed=outcome.replayed,
    )


@router.get("/submissions/{submission_id}", response_model=sb.Submission)
async def get_submission(
    submission_id: IdPath, actor: Actor, services: ServicesDep
) -> JSONResponse:
    return respond(
        presenters.submission(await services.sessions.get_submission(actor, submission_id))
    )
