"""Assessment and mastery reads (Step 18.4). There is no write path: assessments come only
from the worker's AssessmentService commit."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.api import presenters
from app.api.dependencies.auth import Actor, ServicesDep
from app.api.responses import respond
from app.api.routes.params import COURSE_PATTERN, ID_PATTERN, Cursor, IdPath, Limit, page
from app.domain.types.common import DEFAULT_PAGE_LIMIT
from app.schemas import assessment as a

router = APIRouter(prefix="/api", tags=["assessments"])


@router.get("/assessments/{assessment_id}", response_model=a.Assessment)
async def get_assessment(
    assessment_id: IdPath, actor: Actor, services: ServicesDep
) -> JSONResponse:
    return respond(
        presenters.assessment(await services.assessments.get_assessment(actor, assessment_id))
    )


@router.get("/assessments", response_model=a.AssessmentList)
async def list_assessments(
    actor: Actor,
    services: ServicesDep,
    session_id: Annotated[str, Query(alias="sessionId", pattern=ID_PATTERN, max_length=128)],
    cursor: Cursor = None,
    limit: Limit = DEFAULT_PAGE_LIMIT,
) -> JSONResponse:
    result = await services.assessments.list_for_session(actor, session_id, page(cursor, limit))
    return respond(
        a.AssessmentList(
            assessments=[presenters.assessment(x) for x in result.items],
            next_cursor=result.next_cursor,
        )
    )


@router.get("/mastery", response_model=a.MasteryList)
async def list_mastery(
    actor: Actor,
    services: ServicesDep,
    course_id: Annotated[str, Query(alias="courseId", pattern=COURSE_PATTERN)],
    cursor: Annotated[str | None, Query(max_length=128)] = None,
    limit: Limit = DEFAULT_PAGE_LIMIT,
) -> JSONResponse:
    result = await services.mastery.list_for_course(actor, course_id, page(cursor, limit))
    return respond(
        a.MasteryList(
            mastery=[presenters.mastery(x) for x in result.items], next_cursor=result.next_cursor
        )
    )
