"""Organization question bank (Step 45, API.md §6.5.7).

Authors and content reviewers of one organization. Students, parents, platform reviewers
and admins get 403; another organization's items return 404. Every POST/PATCH needs an
Idempotency-Key. Bank data and answer keys never appear in any student response.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse

from app.api.dependencies.auth import Platform, ServicesDep
from app.api.dependencies.commands import IdempotencyKeyHeader, command_key
from app.api.responses import respond
from app.api.routes.packages import version_view
from app.domain.bank_entry_service import BatchPassage, BatchQuestion, BatchSettings
from app.domain.bank_import_service import NewSource
from app.domain.bank_service import CreateItemInput, ItemDetail
from app.domain.ports.bank import ItemQuery
from app.domain.selection_service import SelectionInput, SetInput
from app.domain.types.actor import Permission
from app.domain.types.assistant import AssistantTurn, TurnMode
from app.domain.types.bank import (
    AnswerSource,
    BankItem,
    BankItemState,
    BankItemVersion,
    BankSource,
    FigureMode,
    ImportJob,
    ItemContent,
    ItemType,
    Provenance,
    ProvenanceKind,
    Selection,
    SourceKind,
    SourcePage,
    SourceType,
)
from app.schemas import bank as bk
from app.schemas.package import EmptyCommand

router = APIRouter(prefix="/api/bank", tags=["bank"])

ItemPath = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]

# API field name → domain field name (only where they differ)
_FIELD = {"type": "item_type"}


def _content(c: bk.ItemContentIn) -> ItemContent:
    return ItemContent(
        section=c.section,
        skill_ids=tuple(c.skill_ids),
        difficulty=c.difficulty,
        passage_id=c.passage_id,
        stem=c.stem,
        item_type=ItemType(c.type),
        choices={str(k): v for k, v in c.choices.items()} if c.choices is not None else None,
        answer=c.answer,
        answer_source=AnswerSource(c.answer_source) if c.answer_source else None,
        solution=c.solution,
        figure=FigureMode(c.figure),
        flags=tuple(c.flags),
    )


def _changes(c: bk.ItemChangesIn) -> dict[str, Any]:
    """Only fields the client sent; enums converted to domain values."""
    out: dict[str, Any] = {}
    for name in c.model_fields_set:
        value = getattr(c, name)
        if name == "type":
            value = ItemType(value) if value is not None else ItemType.MC
        elif name == "answer_source":
            value = AnswerSource(value) if value is not None else None
        elif name == "figure":
            value = FigureMode(value) if value is not None else FigureMode.NONE
        elif name in ("skill_ids", "flags", "tags"):
            value = tuple(value or ())
        elif name == "choices":
            value = dict(value) if value is not None else None
        elif name == "stem":
            value = value or ""
        out[_FIELD.get(name, name)] = value
    return out


def _provenance_view(p: Provenance) -> bk.ProvenanceView:
    return bk.ProvenanceView(
        kind=p.kind.value,
        source_id=p.source_id,
        page=p.page,
        region=p.region,
        import_job_id=p.import_job_id,
        reference=p.reference,
    )


def _version_view(v: BankItemVersion) -> bk.ItemVersionView:
    c, p, r = v.content, v.provenance, v.review
    return bk.ItemVersionView(
        number=v.number,
        state=v.state.value,
        section=c.section,
        skill_ids=list(c.skill_ids),
        difficulty=c.difficulty,
        passage_id=c.passage_id,
        stem=c.stem,
        type=c.item_type.value,
        choices=dict(c.choices) if c.choices is not None else None,
        answer=c.answer,
        answer_source=c.answer_source.value if c.answer_source else None,
        solution=c.solution,
        figure=c.figure.value,
        flags=list(c.flags),
        provenance=bk.ProvenanceView(
            kind=p.kind.value,
            source_id=p.source_id,
            page=p.page,
            region=p.region,
            import_job_id=p.import_job_id,
            reference=p.reference,
        ),
        created_by=v.created_by,
        created_at=v.created_at,
        updated_at=v.updated_at,
        submitted_by=v.submitted_by,
        submitted_at=v.submitted_at,
        review=None
        if r is None
        else bk.ItemReviewView(
            reviewer_id=r.reviewer_id,
            decision=r.decision.value,  # type: ignore[arg-type]
            decided_at=r.decided_at,
            notes=r.notes,
        ),
    )


def _summary(i: BankItem) -> bk.BankItemSummaryView:
    return bk.BankItemSummaryView(
        item_id=i.item_id,
        course_id=i.course_id,
        state=i.state.value,
        current_version=i.current_version,
        approved_version=i.approved_version,
        revision=i.revision,
        tags=list(i.tags),
        flags=list(i.flags),
        updated_at=i.updated_at,
    )


def item_view(d: ItemDetail) -> bk.BankItemView:
    i = d.item
    return bk.BankItemView(
        **_summary(i).model_dump(),
        org_id=i.org_id,
        created_by=i.created_by,
        created_at=i.created_at,
        current=_version_view(d.current),
        versions=[_version_view(v) for v in d.versions],
        history=[
            bk.ItemChangeView(
                action=h.action,
                version=h.version,
                actor_id=h.actor_id,
                at=h.at,
                from_state=h.from_state.value if h.from_state else None,
                to_state=h.to_state.value if h.to_state else None,
                notes=h.notes,
            )
            for h in i.history
        ],
    )


# ---- Reads ------------------------------------------------------------------------------------


@router.get("/me", response_model=bk.BankMemberView)
async def bank_member(actor: Platform) -> JSONResponse:
    actor.require(Permission.BANK_AUTHOR)
    assert actor.org_id is not None  # bank:author implies an organization
    return respond(
        bk.BankMemberView(
            uid=actor.actor_id,
            role=actor.role.value,  # type: ignore[arg-type]
            org_id=actor.org_id,
            can_review=actor.can(Permission.BANK_REVIEW),
        )
    )


# ---- Quick entry and imports (Step 39A) ------------------------------------------------------


def _import_view(j: ImportJob) -> bk.ImportJobView:
    return bk.ImportJobView(
        job_id=j.job_id,
        kind=j.kind.value,
        status=j.status.value,
        pages=[
            bk.ImportPageView(
                source_id=p.source_id,
                page=p.page,
                status=p.status.value,
                item_ids=list(p.item_ids),
                method=p.method,
                error=p.error,
            )
            for p in j.pages
        ],
        estimate_tokens=j.estimate_tokens,
        tokens_used=j.tokens_used,
        key_origin=j.key_origin.value if j.key_origin else None,
        item_count=j.item_count,
        item_ids=list(j.item_ids),
        passage_ids=list(j.passage_ids),
        skipped=list(j.skipped),
        errors=list(j.errors),
        source_title=j.source_title,
        course_id=j.course_hint,
        created_by=j.created_by,
        created_at=j.created_at,
    )


@router.post("/imports/parse", response_model=bk.ParseView)
async def parse_import(
    body: bk.ParseRequest, actor: Platform, services: ServicesDep
) -> JSONResponse:
    """Split pasted text or CSV into proposed questions. Writes nothing, so it needs no
    Idempotency-Key."""
    preview = await services.bank_entry.preview(actor, body.format, body.text)
    return respond(
        bk.ParseView(
            questions=[
                bk.ProposedQuestionView(
                    number=q.number,
                    passage_ref=q.passage_ref,
                    content=bk.ItemContentView(
                        section=q.section,
                        skill_ids=list(q.skill_ids),
                        difficulty=q.difficulty,
                        stem=q.stem,
                        type=q.item_type,
                        choices=dict(q.choices) if q.choices else None,
                        answer=q.answer,
                        solution=q.solution,
                    ),
                    problems=list(q.problems),
                    duplicate_of=preview.duplicates.get(q.number),
                )
                for q in preview.result.questions
            ],
            passages=[
                bk.ProposedPassageView(
                    ref=p.ref,
                    title=p.title,
                    text=p.text,
                    range_from=p.range_from,
                    range_to=p.range_to,
                )
                for p in preview.result.passages
            ],
            problems=list(preview.result.problems),
        )
    )


@router.post("/imports/batch", response_model=bk.ImportJobView, status_code=201)
async def import_batch(
    body: bk.BatchRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    st = body.settings
    outcome = await services.bank_entry.import_batch(
        actor,
        [
            BatchQuestion(number=q.number, content=_content(q.content), passage_ref=q.passage_ref)
            for q in body.questions
        ],
        [BatchPassage(ref=p.ref, title=p.title, text=p.text) for p in body.passages],
        BatchSettings(
            course_id=st.course_id,
            section=st.section,
            skill_ids=tuple(st.skill_ids),
            difficulty=st.difficulty,
            key_origin=AnswerSource(st.key_origin),
            source_title=st.source_title,
            source_license=st.source_license,
            tags=tuple(st.tags),
        ),
        cmd,
        keep_duplicates=body.keep_duplicates,
    )
    return respond(_import_view(outcome.value), status=201, replayed=outcome.replayed)


def _source_view(x: BankSource, uploaded: int) -> bk.SourceView:
    return bk.SourceView(
        source_id=x.source_id,
        kind=x.kind.value,
        title=x.title,
        url=x.url,
        page_count=x.page_count,
        pages_uploaded=uploaded,
        license=x.license,
        used_by_job=x.used_by_job,
        created_at=x.created_at,
    )


def _page_view(p: SourcePage) -> bk.PageView:
    return bk.PageView(
        source_id=p.source_id,
        number=p.number,
        media_type=p.media_type,
        data_base64=p.data_base64,
        text=p.text,
    )


@router.post("/sources", response_model=bk.SourceView, status_code=201)
async def create_source(
    body: bk.CreateSourceRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.imports.create_source(
        actor,
        NewSource(
            kind=SourceKind(body.kind),
            title=body.title,
            license=body.license,
            url=body.url,
            text=body.text,
            page_count=body.page_count,
        ),
        cmd,
    )
    s = outcome.value
    uploaded = 1 if s.kind in (SourceKind.TEXT, SourceKind.LINK) else 0
    if outcome.replayed:
        _, uploaded = await services.imports.get_source(actor, s.source_id)
    return respond(_source_view(s, uploaded), status=201, replayed=outcome.replayed)


@router.get("/sources/{source_id}", response_model=bk.SourceView)
async def get_source(source_id: ItemPath, actor: Platform, services: ServicesDep) -> JSONResponse:
    source, uploaded = await services.imports.get_source(actor, source_id)
    return respond(_source_view(source, uploaded))


@router.put("/sources/{source_id}/pages/{number}", response_model=bk.PageView)
async def put_page(
    source_id: ItemPath,
    number: Annotated[int, Path(ge=1, le=200)],
    body: bk.PageRequest,
    actor: Platform,
    services: ServicesDep,
) -> JSONResponse:
    page = await services.imports.put_page(
        actor,
        source_id,
        number,
        media_type=body.media_type,
        data_base64=body.data_base64,
        text=body.text,
    )
    return respond(_page_view(page))


@router.get("/sources/{source_id}/pages/{number}", response_model=bk.PageView)
async def get_page(
    source_id: ItemPath,
    number: Annotated[int, Path(ge=1, le=200)],
    actor: Platform,
    services: ServicesDep,
) -> JSONResponse:
    return respond(_page_view(await services.imports.get_page(actor, source_id, number)))


@router.post("/imports", response_model=bk.ImportJobView, status_code=202)
async def start_import(
    body: bk.StartImportRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.imports.start_import(
        actor,
        body.source_ids,
        cmd,
        course_id=body.course_id,
        key_origin=AnswerSource(body.key_origin),
    )
    return respond(_import_view(outcome.value), status=202, replayed=outcome.replayed)


def _turn_view(t: AssistantTurn) -> bk.TurnView:
    return bk.TurnView(
        turn_id=t.turn_id,
        mode=t.mode.value,
        message=t.message,
        status=t.status.value,
        item_ids=list(t.item_ids),
        source_ids=list(t.source_ids),
        selection_id=t.selection_id,
        course_id=t.context.course_id,
        reply=t.reply,
        error=t.error,
        proposals=[
            bk.ProposalView(
                index=p.index,
                kind=p.kind.value,
                summary=p.summary,
                payload=dict(p.payload),
                status=p.status.value,
                decided_by=p.decided_by,
                result=p.result,
            )
            for p in t.proposals
        ],
        tokens_used=t.tokens_used,
        created_at=t.created_at,
    )


@router.post("/assistant/turns", response_model=bk.TurnView, status_code=202)
async def ask_assistant(
    body: bk.AskRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.assistant.ask(
        actor,
        body.message,
        cmd,
        mode=TurnMode(body.mode),
        item_ids=body.item_ids,
        source_ids=body.source_ids,
        course_id=body.course_id,
        selection_id=body.selection_id,
    )
    return respond(_turn_view(outcome.value), status=202, replayed=outcome.replayed)


@router.get("/assistant/turns", response_model=bk.TurnListView)
async def list_turns(actor: Platform, services: ServicesDep) -> JSONResponse:
    turns = await services.assistant.list(actor)
    return respond(bk.TurnListView(turns=[_turn_view(t) for t in turns]))


@router.get("/assistant/turns/{turn_id}", response_model=bk.TurnView)
async def get_turn(turn_id: ItemPath, actor: Platform, services: ServicesDep) -> JSONResponse:
    return respond(_turn_view(await services.assistant.get(actor, turn_id)))


@router.post("/assistant/turns/{turn_id}/proposals/{index}/{decision}", response_model=bk.TurnView)
async def decide_proposal(
    turn_id: ItemPath,
    index: Annotated[int, Path(ge=0, le=50)],
    decision: Annotated[str, Path(pattern="^(accept|reject)$")],
    body: EmptyCommand,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    """Accept or reject one proposal. The Idempotency-Key is checked for shape; the
    decision itself is idempotent (accepting twice is a no-op)."""
    command_key(request, idempotency_key, body)
    if decision == "accept":
        turn = await services.assistant.accept(actor, turn_id, index)
    else:
        turn = await services.assistant.reject(actor, turn_id, index)
    return respond(_turn_view(turn))


@router.get("/imports", response_model=bk.ImportJobListView)
async def list_imports(actor: Platform, services: ServicesDep) -> JSONResponse:
    jobs = await services.bank_entry.list_imports(actor)
    return respond(bk.ImportJobListView(imports=[_import_view(j) for j in jobs]))


@router.get("/imports/{job_id}", response_model=bk.ImportJobView)
async def get_import(job_id: ItemPath, actor: Platform, services: ServicesDep) -> JSONResponse:
    return respond(_import_view(await services.bank_entry.get_import(actor, job_id)))


@router.get("/items", response_model=bk.BankItemListView)
async def list_items(
    actor: Platform,
    services: ServicesDep,
    state: Annotated[bk.ItemStateValue | None, Query()] = None,
    course_id: Annotated[str | None, Query(alias="courseId", max_length=64)] = None,
    flag: Annotated[str | None, Query(max_length=120)] = None,
    approved_only: Annotated[bool, Query(alias="approvedOnly")] = False,
    cursor: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9_-]{1,64}$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> JSONResponse:
    items = await services.bank.list_items(
        actor,
        ItemQuery(
            state=BankItemState(state) if state else None,
            course_id=course_id,
            flag=flag,
            approved_only=approved_only,
            after_item_id=cursor,
            limit=limit,
        ),
    )
    next_cursor = items[-1].item_id if len(items) == limit else None
    return respond(bk.BankItemListView(items=[_summary(i) for i in items], next_cursor=next_cursor))


@router.get("/items/{item_id}", response_model=bk.BankItemView)
async def get_item(item_id: ItemPath, actor: Platform, services: ServicesDep) -> JSONResponse:
    return respond(item_view(await services.bank.get_item(actor, item_id)))


PassagePath = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


@router.get("/passages/{passage_id}", response_model=bk.BankPassageView)
async def get_passage(
    passage_id: PassagePath, actor: Platform, services: ServicesDep
) -> JSONResponse:
    p = await services.bank.get_passage(actor, passage_id)
    return respond(
        bk.BankPassageView(
            passage_id=p.passage_id,
            title=p.title,
            text=p.text,
            provenance=_provenance_view(p.provenance),
            flags=list(p.flags),
            created_by=p.created_by,
            created_at=p.created_at,
        )
    )


# ---- Author commands ------------------------------------------------------------------------


@router.post("/items", response_model=bk.BankItemView, status_code=201)
async def create_item(
    body: bk.CreateItemRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    prov = body.provenance
    provenance = (
        Provenance(
            kind=ProvenanceKind(prov.kind),
            source_id=prov.source_id,
            page=prov.page,
            region=prov.region,
            reference=prov.reference,
        )
        if prov is not None
        else None
    )
    outcome = await services.bank.create(
        actor,
        CreateItemInput(
            content=_content(body.content),
            course_id=body.course_id,
            tags=tuple(body.tags),
            provenance=provenance,
        ),
        cmd,
    )
    return respond(
        item_view(outcome.value), status=201 if outcome.created else 200, replayed=outcome.replayed
    )


@router.patch("/items/{item_id}", response_model=bk.BankItemView)
async def edit_item(
    item_id: ItemPath,
    body: bk.EditItemRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.bank.edit(
        actor, item_id, body.expected_revision, _changes(body.changes), cmd
    )
    return respond(item_view(outcome.value), replayed=outcome.replayed)


@router.post("/items/{item_id}/confirm", response_model=bk.BankItemView)
async def confirm_item(
    item_id: ItemPath,
    body: EmptyCommand,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.bank.confirm(actor, item_id, cmd)
    return respond(item_view(outcome.value), replayed=outcome.replayed)


@router.post("/items/{item_id}/submit", response_model=bk.BankItemView)
async def submit_item(
    item_id: ItemPath,
    body: EmptyCommand,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.bank.submit(actor, item_id, cmd)
    return respond(item_view(outcome.value), replayed=outcome.replayed)


@router.post("/items/{item_id}/discard", response_model=bk.BankItemView)
async def discard_item(
    item_id: ItemPath,
    body: bk.DiscardRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.bank.discard(actor, item_id, cmd, body.notes)
    return respond(item_view(outcome.value), replayed=outcome.replayed)


# ---- Content reviewer commands --------------------------------------------------------------


@router.post("/items/{item_id}/key", response_model=bk.BankItemView)
async def key_item(
    item_id: ItemPath,
    body: bk.KeyRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.bank.set_key(actor, item_id, body.answer, body.solution, cmd)
    return respond(item_view(outcome.value), replayed=outcome.replayed)


@router.post("/items/{item_id}/approve", response_model=bk.BankItemView)
async def approve_item(
    item_id: ItemPath,
    body: bk.ApproveItemRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.bank.approve(actor, item_id, body.notes, cmd)
    return respond(item_view(outcome.value), replayed=outcome.replayed)


@router.post("/items/{item_id}/reject", response_model=bk.BankItemView)
async def reject_item(
    item_id: ItemPath,
    body: bk.NotesRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.bank.reject(actor, item_id, body.notes, cmd)
    return respond(item_view(outcome.value), replayed=outcome.replayed)


@router.post("/items/{item_id}/retire", response_model=bk.BankItemView)
async def retire_item(
    item_id: ItemPath,
    body: bk.NotesRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.bank.retire(actor, item_id, body.notes, cmd)
    return respond(item_view(outcome.value), replayed=outcome.replayed)


# ---- Selections and builds (Step 45.4) ----------------------------------------------------------

SelectionPath = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


def _selection_input(s: bk.SelectionIn) -> SelectionInput:
    return SelectionInput(
        name=s.name,
        sets=[
            SetInput(
                set_id=st.set_id,
                title=st.title,
                task_title=st.task_title,
                duration_min=st.duration_min,
                items=[(r.item_id, r.version) for r in st.items],
                skill_ids=tuple(st.skill_ids),
                difficulty=st.difficulty,
            )
            for st in s.sets
        ],
        starter_set_ids=tuple(s.starter_set_ids),
        sequence_set_ids=tuple(s.sequence_set_ids),
        source_type=SourceType(s.source_type),
        source_author=s.source_author,
        source_license=s.source_license,
        added_skills=tuple(
            {"skillId": k.skill_id, "name": k.name, "description": k.description}
            for k in s.added_skills
        ),
    )


def selection_view(x: Selection) -> bk.SelectionView:
    return bk.SelectionView(
        selection_id=x.selection_id,
        course_id=x.course_id,
        name=x.name,
        sets=[
            bk.SelectionSetView(
                set_id=st.set_id,
                title=st.title,
                task_title=st.task_title,
                duration_min=st.duration_min,
                items=[bk.ItemRefView(item_id=r.item_id, version=r.version) for r in st.items],
                skill_ids=list(st.skill_ids),
                difficulty=st.difficulty,
            )
            for st in x.sets
        ],
        starter_set_ids=list(x.starter_set_ids),
        sequence_set_ids=list(x.sequence_set_ids),
        source_type=x.source_type.value,
        source_author=x.source_author,
        source_license=x.source_license,
        added_skills=[
            bk.AddedSkillView(
                skill_id=k["skillId"], name=k["name"], description=k.get("description", "")
            )
            for k in x.added_skills
        ],
        revision=x.revision,
        created_by=x.created_by,
        created_at=x.created_at,
        updated_at=x.updated_at,
        built_package_version=x.built_package_version,
        built_by=x.built_by,
        built_at=x.built_at,
    )


@router.get("/selections", response_model=bk.SelectionListView)
async def list_selections(actor: Platform, services: ServicesDep) -> JSONResponse:
    items = await services.selections.list(actor)
    return respond(bk.SelectionListView(selections=[selection_view(x) for x in items]))


@router.get("/selections/{selection_id}", response_model=bk.SelectionView)
async def get_selection(
    selection_id: SelectionPath, actor: Platform, services: ServicesDep
) -> JSONResponse:
    return respond(selection_view(await services.selections.get(actor, selection_id)))


@router.post("/selections", response_model=bk.SelectionView, status_code=201)
async def create_selection(
    body: bk.CreateSelectionRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.selections.create(actor, body.course_id, _selection_input(body), cmd)
    return respond(
        selection_view(outcome.value),
        status=201 if outcome.created else 200,
        replayed=outcome.replayed,
    )


@router.patch("/selections/{selection_id}", response_model=bk.SelectionView)
async def update_selection(
    selection_id: SelectionPath,
    body: bk.UpdateSelectionRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.selections.update(
        actor, selection_id, body.expected_revision, _selection_input(body.selection), cmd
    )
    return respond(selection_view(outcome.value), replayed=outcome.replayed)


@router.post("/selections/{selection_id}/build", response_model=bk.BuildView, status_code=201)
async def build_selection(
    selection_id: SelectionPath,
    body: bk.BuildRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.selections.build(actor, selection_id, body.version, cmd)
    view = bk.BuildView(
        selection=selection_view(outcome.value.selection),
        package=version_view(outcome.value.package),
    )
    return respond(view, status=201, replayed=outcome.replayed)
