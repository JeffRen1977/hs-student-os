"""Authoring assistant (Step 40, QUESTION_BANK.md §4.5, §7.2).

- `ask` snapshots what the user selected and queues a turn. Bank mode (40A) is for authors
  and content reviewers; design mode (40B) is for the content reviewer of the organization.
- `AssistantProcessor` (local worker tick; Cloud Scheduler when deployed) leases a turn,
  calls the `authoring-assistant` ability outside any transaction (organization budget) and
  stores the reply and proposals in a transaction fenced by the lease.
- `accept` applies one proposal through the normal bank or selection commands as the
  accepting user, with an Idempotency-Key derived from the turn and proposal, so a retry
  after a crash replays instead of applying twice; then marks it accepted. An edit whose item
  changed since the snapshot fails with VERSION_CONFLICT. A key accepted by an author is
  recorded as `agent-suggested` (the content reviewer must still confirm it); accepted by the
  content reviewer it becomes the reviewer key. `reject` changes nothing in the bank.
Turns are visible only to the person who asked (others get 404).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import timedelta
from typing import Any

from app.domain.bank_service import BankService, CreateItemInput
from app.domain.commands import CommandKey, Outcome
from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.bank import BankTx, BankUnitOfWork, ImportQueueReader, ItemQuery
from app.domain.ports.execution import ExecutionFailure, RetryableExecutionError
from app.domain.ports.llm import BudgetExceededError, LlmGateway
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.selection_service import SelectionInput, SelectionService, SetInput
from app.domain.skills import authoring_assistant as ability
from app.domain.types.actor import Permission, PlatformActor
from app.domain.types.assistant import (
    AssistantTurn,
    Proposal,
    ProposalKind,
    ProposalStatus,
    TurnContext,
    TurnMode,
)
from app.domain.types.bank import (
    AnswerSource,
    BankItemState,
    FigureMode,
    ImportLease,
    ImportStatus,
    ItemContent,
    ItemType,
    Provenance,
    ProvenanceKind,
)
from app.domain.types.common import IdempotencyRecord

logger = logging.getLogger(__name__)

TURN_RESOURCE = "assistant_turn"
MAX_ITEMS = 20
MAX_DESIGN_ITEMS = 150
MAX_PAGES = 3
MAX_MESSAGE_CHARS = 20_000
BUDGET_MESSAGE = "The organization's model budget for authoring is used up; try again tomorrow."


def _invalid(message: str) -> DomainError:
    return DomainError(ErrorCode.VALIDATION_FAILED, message)


def _org(actor: PlatformActor) -> str:
    if actor.org_id is None:  # pragma: no cover
        raise DomainError(ErrorCode.FORBIDDEN, "Not a member of an author organization.")
    return actor.org_id


def _content_view(c: ItemContent) -> dict[str, Any]:
    return {
        "stem": c.stem[:4_000],
        "type": c.item_type.value,
        "choices": dict(c.choices) if c.choices else None,
        "answer": c.answer,
        "answerSource": c.answer_source.value if c.answer_source else None,
        "solution": (c.solution or "")[:2_000] or None,
        "section": c.section,
        "skillIds": list(c.skill_ids),
        "difficulty": c.difficulty,
        "flags": list(c.flags),
    }


def _not_found() -> DomainError:
    return DomainError(ErrorCode.NOT_FOUND, "Assistant turn not found.")


class AssistantService:
    def __init__(
        self,
        uow: BankUnitOfWork,
        bank: BankService,
        selections: SelectionService,
        clock: Clock,
        ids: IdFactory,
        *,
        model_available: bool,
    ) -> None:
        self._uow = uow
        self._bank = bank
        self._selections = selections
        self._clock = clock
        self._ids = ids
        self._model = model_available

    async def ask(
        self,
        actor: PlatformActor,
        message: str,
        cmd: CommandKey,
        *,
        mode: TurnMode = TurnMode.BANK,
        item_ids: Sequence[str] = (),
        source_ids: Sequence[str] = (),
        course_id: str | None = None,
        selection_id: str | None = None,
    ) -> Outcome[AssistantTurn]:
        actor.require(Permission.BANK_AUTHOR)
        if mode is TurnMode.DESIGN:
            actor.require(Permission.BANK_REVIEW)
        org = _org(actor)
        if not self._model:
            raise DomainError(
                ErrorCode.VALIDATION_FAILED, "The assistant needs a model; none is configured here."
            )
        if not message.strip() or len(message) > MAX_MESSAGE_CHARS:
            raise _invalid(f"Write a request of at most {MAX_MESSAGE_CHARS} characters.")
        if len(set(item_ids)) > MAX_ITEMS or len(source_ids) > 3:
            raise _invalid(f"Select at most {MAX_ITEMS} items and 3 sources.")
        selection = None
        if selection_id is not None:
            selection = await self._selections.get(actor, selection_id)
            course_id = selection.course_id
        if mode is TurnMode.DESIGN and not course_id:
            raise _invalid("Name the course (or the selection) to design for.")

        async def snapshot(
            tx: BankTx,
        ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
            items: list[dict[str, Any]] = []
            course = course_id
            if mode is TurnMode.DESIGN:
                found = await tx.items.query(
                    org, ItemQuery(course_id=course, approved_only=True, limit=MAX_DESIGN_ITEMS)
                )
                for hit in found:
                    v = await tx.items.get_version(org, hit.item_id, hit.approved_version or 1)
                    if v is not None:
                        items.append(
                            {
                                "itemId": hit.item_id,
                                "revision": hit.revision,
                                "state": hit.state.value,
                                "version": v.number,
                                "content": _content_view(v.content),
                                "passageId": v.content.passage_id,
                            }
                        )
            for iid in dict.fromkeys(item_ids):
                it = await tx.items.get(org, iid)
                if it is None:
                    raise DomainError(ErrorCode.NOT_FOUND, f"Item {iid} not found.")
                v = await tx.items.get_version(org, iid, it.current_version)
                if v is None:  # pragma: no cover
                    continue
                passage = None
                if v.content.passage_id:
                    p = await tx.passages.get(org, v.content.passage_id)
                    passage = p.text[:6_000] if p else None
                course = course or it.course_id
                items.append(
                    {
                        "itemId": iid,
                        "revision": it.revision,
                        "state": it.state.value,
                        "content": _content_view(v.content),
                        "passage": passage,
                    }
                )
            pages: list[dict[str, Any]] = []
            for sid in source_ids:
                source = await tx.sources.get(org, sid)
                if source is None:
                    raise DomainError(ErrorCode.NOT_FOUND, f"Source {sid} not found.")
                for n in list(await tx.sources.page_numbers(org, sid))[:MAX_PAGES]:
                    if len(pages) >= MAX_PAGES:
                        break
                    page = await tx.sources.get_page(org, sid, n)
                    if page is not None:
                        pages.append(
                            {
                                "sourceId": sid,
                                "page": n,
                                "text": (page.text or "")[:8_000],
                                "hasImage": bool(page.data_base64),
                            }
                        )
            return items, pages, course

        items, pages, course = await self._uow.transaction(snapshot)
        skills = list(await self._selections.base_skills(actor, course)) if course else []
        context = TurnContext(
            items=items,
            pages=pages,
            skills=skills,
            course_id=course,
            selection=_selection_view(selection) if selection else None,
        )

        async def write(tx: BankTx) -> Outcome[AssistantTurn]:
            record = await tx.idempotency.get(actor.actor_id, cmd.key_hash(actor))
            if record is not None:
                if record.scope != cmd.scope or record.request_digest != cmd.request_digest:
                    raise DomainError(
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "This Idempotency-Key was already used with a different request.",
                    )
                existing = await tx.turns.get(org, record.resource_id)
                if existing is None:  # pragma: no cover
                    raise _not_found()
                return Outcome(value=existing, replayed=True, created=True)
            now = self._clock.now()
            turn = AssistantTurn(
                turn_id=self._ids.new("trn"),
                org_id=org,
                created_by=actor.actor_id,
                mode=mode,
                message=message.strip(),
                status=ImportStatus.QUEUED,
                created_at=now,
                updated_at=now,
                context=context,
                item_ids=tuple(dict.fromkeys(item_ids)),
                source_ids=tuple(source_ids),
                selection_id=selection_id,
            )
            tx.turns.save(turn)
            tx.idempotency.save(
                actor.actor_id,
                IdempotencyRecord(
                    key_hash=cmd.key_hash(actor),
                    scope=cmd.scope,
                    request_digest=cmd.request_digest,
                    resource_type=TURN_RESOURCE,
                    resource_id=turn.turn_id,
                    response_status=202,
                    created_at=now,
                ),
            )
            return Outcome(value=turn, created=True)

        return await self._uow.transaction(write)

    async def get(self, actor: PlatformActor, turn_id: str) -> AssistantTurn:
        actor.require(Permission.BANK_AUTHOR)
        org = _org(actor)

        async def read(tx: BankTx) -> AssistantTurn:
            turn = await tx.turns.get(org, turn_id)
            if turn is None or turn.created_by != actor.actor_id:
                raise _not_found()
            return turn

        return await self._uow.transaction(read)

    async def list(self, actor: PlatformActor) -> Sequence[AssistantTurn]:
        actor.require(Permission.BANK_AUTHOR)
        org = _org(actor)

        async def read(tx: BankTx) -> Sequence[AssistantTurn]:
            return await tx.turns.list_for_user(org, actor.actor_id, 20)

        return await self._uow.transaction(read)

    async def reject(self, actor: PlatformActor, turn_id: str, index: int) -> AssistantTurn:
        return await self._decide(actor, turn_id, index, ProposalStatus.REJECTED, None)

    async def accept(self, actor: PlatformActor, turn_id: str, index: int) -> AssistantTurn:
        turn = await self.get(actor, turn_id)
        if not 0 <= index < len(turn.proposals):
            raise DomainError(ErrorCode.NOT_FOUND, "Proposal not found.")
        proposal = turn.proposals[index]
        if proposal.status is ProposalStatus.ACCEPTED:
            return turn  # accepting twice is a no-op
        if proposal.status is ProposalStatus.REJECTED:
            raise DomainError(ErrorCode.INVALID_STATE_TRANSITION, "This proposal was rejected.")
        if proposal.kind in (ProposalKind.SELECTION_SETS, ProposalKind.ADD_SKILL):
            actor.require(Permission.BANK_REVIEW)
        result = await self._apply(actor, turn, proposal)
        return await self._decide(actor, turn_id, index, ProposalStatus.ACCEPTED, result)

    # ---- applying proposals --------------------------------------------------------------

    def _cmd(self, turn: AssistantTurn, p: Proposal, part: str = "") -> CommandKey:
        digest = hashlib.sha256(json.dumps(p.payload, sort_keys=True, default=str).encode())
        return CommandKey(
            scope=f"assistant-accept{part}",
            key=f"{turn.turn_id}:{p.index}{part}",
            request_digest=digest.hexdigest(),
        )

    async def _apply(self, actor: PlatformActor, turn: AssistantTurn, p: Proposal) -> str | None:
        d = p.payload
        if p.kind is ProposalKind.CREATE_ITEM:
            passage_id = None
            if d.get("passageText"):
                made = await self._bank.create_passage(
                    actor,
                    d.get("passageTitle") or "Passage",
                    d["passageText"],
                    Provenance(
                        kind=ProvenanceKind.AGENT_DRAFTED, reference=f"assistant {turn.turn_id}"
                    ),
                    self._cmd(turn, p, ":passage"),
                )
                passage_id = made.value.passage_id
            kind = ProvenanceKind.AGENT_DRAFTED if d.get("drafted") else ProvenanceKind.IMPORTED
            content = ItemContent(
                stem=d["stem"],
                item_type=ItemType.MC if d.get("choices") else ItemType.SPR,
                choices=d.get("choices"),
                answer=d.get("answer"),
                answer_source=AnswerSource.AGENT_SUGGESTED if d.get("answer") else None,
                solution=d.get("solution"),
                skill_ids=tuple(d.get("skillIds") or ()),
                difficulty=d.get("difficulty"),
                passage_id=passage_id,
                figure=FigureMode.DESCRIBED if "[" in d["stem"] else FigureMode.NONE,
                flags=(
                    "assistant",
                    "agent-drafted" if d.get("drafted") else "assistant-transcribed",
                ),
            )
            created = await self._bank.create(
                actor,
                CreateItemInput(
                    content=content,
                    course_id=turn.context.course_id,
                    provenance=Provenance(kind=kind, reference=f"assistant {turn.turn_id}"),
                ),
                self._cmd(turn, p),
                initial_state=BankItemState.EXTRACTED,
            )
            return created.value.item.item_id
        if p.kind is ProposalKind.EDIT_ITEM:
            names = {"skillIds": "skill_ids"}
            changes: dict[str, Any] = {}
            for k, v in d["changes"].items():
                if k == "figure":
                    v = FigureMode(v) if v in ("none", "described", "image") else FigureMode.NONE
                elif k == "skillIds":
                    v = tuple(v)
                changes[names.get(k, k)] = v
            await self._bank.edit(
                actor, d["itemId"], d["basedOnRevision"], changes, self._cmd(turn, p)
            )
            return str(d["itemId"])
        if p.kind is ProposalKind.PROPOSE_KEY:
            if actor.can(Permission.BANK_REVIEW):
                await self._bank.set_key(
                    actor,
                    d["itemId"],
                    d["answer"],
                    d["solution"],
                    self._cmd(turn, p),
                    expected_revision=d["basedOnRevision"],
                )
            else:
                await self._bank.edit(
                    actor,
                    d["itemId"],
                    d["basedOnRevision"],
                    {
                        "answer": d["answer"],
                        "answer_source": AnswerSource.AGENT_SUGGESTED,
                        "solution": d["solution"],
                    },
                    self._cmd(turn, p),
                )
            return str(d["itemId"])
        if p.kind is ProposalKind.FLAG:
            item = await self._bank.get_item(actor, d["itemId"])
            flags = (*item.current.content.flags, d["flag"])
            await self._bank.edit(
                actor,
                d["itemId"],
                d["basedOnRevision"],
                {"flags": tuple(dict.fromkeys(flags))},
                self._cmd(turn, p),
            )
            return str(d["itemId"])
        if p.kind is ProposalKind.LINK_PASSAGE:
            made = await self._bank.create_passage(
                actor,
                d.get("title") or "Passage",
                d["text"],
                Provenance(
                    kind=ProvenanceKind.AGENT_DRAFTED, reference=f"assistant {turn.turn_id}"
                ),
                self._cmd(turn, p, ":passage"),
            )
            pid = made.value.passage_id
            for iid in d["itemIds"]:
                await self._bank.edit(
                    actor,
                    iid,
                    d["basedOnRevisions"][iid],
                    {"passage_id": pid},
                    self._cmd(turn, p, f":{iid}"),
                )
            return pid
        if p.kind is ProposalKind.SELECTION_SETS:
            inp = SelectionInput(
                name=d["name"],
                sets=[
                    SetInput(
                        set_id=s["setId"],
                        title=s["title"],
                        task_title=s["taskTitle"],
                        duration_min=20,
                        items=[(i, None) for i in s["itemIds"]],
                        skill_ids=tuple(s["skillIds"]),
                        difficulty=s["difficulty"],
                    )
                    for s in d["sets"]
                ],
                starter_set_ids=[s["setId"] for s in d["sets"] if s["role"] == "starter"],
                sequence_set_ids=[s["setId"] for s in d["sets"] if s["role"] == "sequence"],
            )
            if turn.selection_id:
                current = await self._selections.get(actor, turn.selection_id)
                inp = replace(
                    inp,
                    added_skills=tuple(current.added_skills),
                    source_type=current.source_type,
                    source_author=current.source_author,
                    source_license=current.source_license,
                )
                sel = await self._selections.update(
                    actor, turn.selection_id, current.revision, inp, self._cmd(turn, p)
                )
            else:
                course = turn.context.course_id or ""
                sel = await self._selections.create(actor, course, inp, self._cmd(turn, p))
            return sel.value.selection_id
        if p.kind is ProposalKind.ADD_SKILL:
            target = turn.selection_id or next(
                (
                    q.result
                    for q in turn.proposals
                    if q.kind is ProposalKind.SELECTION_SETS and q.status is ProposalStatus.ACCEPTED
                ),
                None,
            )
            if not target:
                raise _invalid(
                    "Accept the proposed sets first, or ask about an existing selection."
                )
            current = await self._selections.get(actor, target)
            skill = {"skillId": d["skillId"], "name": d["name"], "description": d["description"]}
            added = [k for k in current.added_skills if k["skillId"] != d["skillId"]] + [skill]
            await self._selections.update(
                actor,
                current.selection_id,
                current.revision,
                _selection_input(current, added),
                self._cmd(turn, p),
            )
            return current.selection_id
        raise _invalid("Unknown proposal kind.")  # pragma: no cover

    async def _decide(
        self,
        actor: PlatformActor,
        turn_id: str,
        index: int,
        status: ProposalStatus,
        result: str | None,
    ) -> AssistantTurn:
        actor.require(Permission.BANK_AUTHOR)
        org = _org(actor)

        async def write(tx: BankTx) -> AssistantTurn:
            turn = await tx.turns.get(org, turn_id)
            if turn is None or turn.created_by != actor.actor_id:
                raise _not_found()
            if not 0 <= index < len(turn.proposals):
                raise DomainError(ErrorCode.NOT_FOUND, "Proposal not found.")
            p = turn.proposals[index]
            if p.status is status:
                return turn
            if p.status is not ProposalStatus.OPEN:
                raise DomainError(
                    ErrorCode.INVALID_STATE_TRANSITION,
                    f"This proposal was already {p.status.value}.",
                )
            now = self._clock.now()
            proposals = list(turn.proposals)
            proposals[index] = replace(
                p, status=status, decided_by=actor.actor_id, decided_at=now, result=result
            )
            updated = replace(turn, proposals=tuple(proposals), updated_at=now)
            tx.turns.save(updated)
            return updated

        return await self._uow.transaction(write)


def _selection_view(s: Any) -> dict[str, Any]:
    return {
        "selectionId": s.selection_id,
        "name": s.name,
        "revision": s.revision,
        "sets": [
            {
                "setId": st.set_id,
                "itemIds": [r.item_id for r in st.items],
                "skillIds": list(st.skill_ids),
                "difficulty": st.difficulty,
            }
            for st in s.sets
        ],
        "addedSkills": [dict(k) for k in s.added_skills],
    }


def _selection_input(s: Any, added: Sequence[Mapping[str, str]]) -> SelectionInput:
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
        source_type=s.source_type,
        source_author=s.source_author,
        source_license=s.source_license,
        added_skills=tuple(added),
    )


class StaleTurnLease(Exception):
    pass


class AssistantProcessor:
    def __init__(
        self,
        uow: BankUnitOfWork,
        queue: ImportQueueReader,
        gateway: LlmGateway | None,
        clock: Clock,
        ids: IdFactory,
        *,
        worker_id: str,
        lease_seconds: int = 300,
    ) -> None:
        self._uow = uow
        self._queue = queue
        self._gateway = gateway
        self._clock = clock
        self._ids = ids
        self._worker = worker_id
        self._lease = timedelta(seconds=lease_seconds)

    async def process_due(self, limit: int = 5) -> int:
        done = 0
        for org, turn_id in await self._queue.due_turns(self._clock.now(), limit):
            try:
                await self.run_turn(org, turn_id)
                done += 1
            except StaleTurnLease:
                logger.info("assistant_lease_lost", extra={"turnId": turn_id})
        return done

    async def run_turn(self, org: str, turn_id: str) -> None:
        token = self._ids.new("lease")

        async def claim(tx: BankTx) -> AssistantTurn | None:
            turn = await tx.turns.get(org, turn_id)
            now = self._clock.now()
            if turn is None or turn.status not in (ImportStatus.QUEUED, ImportStatus.RUNNING):
                return None
            if turn.status is ImportStatus.RUNNING and turn.lease and turn.lease.expires_at > now:
                return None
            claimed = replace(
                turn,
                status=ImportStatus.RUNNING,
                updated_at=now,
                lease=ImportLease(
                    worker_id=self._worker, token=token, expires_at=now + self._lease
                ),
            )
            tx.turns.save(claimed)
            return claimed

        turn = await self._uow.transaction(claim)
        if turn is None:
            return
        images = await self._images(org, turn)
        reply: str | None = None
        proposals: tuple[Proposal, ...] = ()
        tokens = 0
        error: str | None = None
        try:
            if self._gateway is None:
                raise ExecutionFailure("MODEL_UNAVAILABLE")
            out = await ability.run_turn(
                self._gateway,
                org_id=org,
                turn_id=turn_id,
                message=turn.message,
                context=turn.context,
                mode=turn.mode,
                images=images,
            )
            reply, tokens = out.reply, out.usage_tokens
            proposals = tuple(
                Proposal(index=i, kind=p.kind, summary=p.summary, payload=p.payload)
                for i, p in enumerate(out.proposals)
            )
        except BudgetExceededError:
            error = BUDGET_MESSAGE
        except (ExecutionFailure, RetryableExecutionError) as exc:
            code = getattr(exc, "code", "")
            error = (
                "The assistant's answer could not be used; ask again, perhaps more simply."
                if code == "MODEL_OUTPUT_INVALID"
                else "The assistant is not available right now; try again later."
            )

        async def commit(tx: BankTx) -> None:
            current = await tx.turns.get(org, turn_id)
            if current is None or current.lease is None or current.lease.token != token:
                raise StaleTurnLease(turn_id)
            tx.turns.save(
                replace(
                    current,
                    status=ImportStatus.FAILED if error else ImportStatus.SUCCEEDED,
                    reply=reply,
                    proposals=proposals,
                    tokens_used=tokens,
                    error=error,
                    lease=None,
                    updated_at=self._clock.now(),
                )
            )

        await self._uow.transaction(commit)

    async def _images(self, org: str, turn: AssistantTurn) -> list[tuple[str, str]]:
        async def read(tx: BankTx) -> list[tuple[str, str]]:
            out: list[tuple[str, str]] = []
            for pg in turn.context.pages:
                if len(out) >= 2 or not pg.get("hasImage"):
                    continue
                page = await tx.sources.get_page(org, pg["sourceId"], int(pg["page"]))
                if page is not None and page.data_base64:
                    out.append((page.media_type or "image/jpeg", page.data_base64))
            return out

        return await self._uow.transaction(read)
