"""Organization question bank: items and their review (Step 45, doc/QUESTION_BANK.md).

- Every operation is scoped to the caller's own organization; another organization's items
  are not found (404).
- Authors (`bank:author`) create, edit, confirm, submit and discard items. Content
  reviewers (`bank:review`, same organization, also authors) additionally set answer keys
  and solutions, edit items in review, approve, reject and retire. A content reviewer may
  approve an item they submitted; submitter and approver are both recorded.
- An item version can be approved only with a final key whose source is `source-key`,
  `compiled-key` or `reviewer`; `agent-suggested` keys must be confirmed by the reviewer.
- Editing an approved or rejected item opens a new draft version; the last approved version
  stays the one selections may use until the new version is approved.
- Every write bumps the item's `revision` (optimistic concurrency), appends to its history
  and is idempotent per Idempotency-Key.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from app.domain.commands import CommandKey, Outcome
from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.bank import BankTx, BankUnitOfWork, ItemQuery
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.types.actor import Permission, PlatformActor
from app.domain.types.bank import (
    APPROVABLE_ANSWER_SOURCES,
    AUTHOR_ANSWER_SOURCES,
    CHOICE_KEYS,
    EDIT_OPENS_VERSION,
    EDITABLE_IN_PLACE,
    ITEM_TRANSITIONS,
    MAX_CHOICE_CHARS,
    MAX_PASSAGE_CHARS,
    MAX_STEM_CHARS,
    AnswerSource,
    BankItem,
    BankItemState,
    BankItemVersion,
    BankPassage,
    ItemChange,
    ItemContent,
    ItemReview,
    ItemType,
    Provenance,
    ProvenanceKind,
    content_hash,
)
from app.domain.types.common import IdempotencyRecord

ITEM_RESOURCE = "bank_item"
PASSAGE_RESOURCE = "bank_passage"
DIFFICULTIES = frozenset({"easy", "medium", "hard"})
MAX_LIST = 200

# Fields of ItemContent an edit may change, plus the header fields `courseId` and `tags`.
CONTENT_FIELDS = frozenset(ItemContent.__dataclass_fields__)
HEADER_FIELDS = frozenset({"course_id", "tags"})


@dataclass(frozen=True, slots=True, kw_only=True)
class ItemDetail:
    """An item header with its current version (and, on reads, every version)."""

    item: BankItem
    current: BankItemVersion
    versions: Sequence[BankItemVersion] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateItemInput:
    content: ItemContent
    course_id: str | None = None
    tags: Sequence[str] = ()
    provenance: Provenance | None = None  # defaults to {kind: author}


def _not_found() -> DomainError:
    return DomainError(ErrorCode.NOT_FOUND, "Item not found.")


def _invalid(message: str) -> DomainError:
    return DomainError(ErrorCode.VALIDATION_FAILED, message)


def check_content(c: ItemContent) -> None:
    """Shape rules that hold for every stored version (complete or not)."""
    if len(c.stem) > MAX_STEM_CHARS:
        raise _invalid(f"stem is longer than {MAX_STEM_CHARS} characters.")
    if c.difficulty is not None and c.difficulty not in DIFFICULTIES:
        raise _invalid("difficulty must be easy, medium or hard.")
    if c.item_type is ItemType.SPR and c.choices:
        raise _invalid("A student-produced-response item has no choices.")
    if c.choices is not None:
        unknown = set(c.choices) - set(CHOICE_KEYS)
        if unknown:
            raise _invalid("choices may only use the keys A, B, C and D.")
        if any(len(v) > MAX_CHOICE_CHARS for v in c.choices.values()):
            raise _invalid(f"a choice is longer than {MAX_CHOICE_CHARS} characters.")
    if c.answer is not None:
        if not c.answer.strip():
            raise _invalid("answer may not be blank; omit it instead.")
        if c.answer_source is None:
            raise _invalid("answerSource is required when an answer is given.")
        if c.item_type is ItemType.MC and c.answer not in CHOICE_KEYS:
            raise _invalid("The answer of a multiple-choice item is one of A, B, C or D.")
    if c.answer is None and c.answer_source is not None:
        raise _invalid("answerSource needs an answer.")


def approval_problems(c: ItemContent) -> tuple[list[str], list[str]]:
    """(missing-key problems, other completeness problems) for approving a version."""
    key: list[str] = []
    other: list[str] = []
    if not c.stem.strip():
        other.append("the stem is empty")
    if c.item_type is ItemType.MC and (
        c.choices is None
        or set(c.choices) != set(CHOICE_KEYS)
        or not all(v.strip() for v in c.choices.values())
    ):
        other.append("a multiple-choice item needs non-empty choices A, B, C and D")
    if c.answer is None:
        key.append("the item has no answer key")
    elif c.answer_source not in APPROVABLE_ANSWER_SOURCES:
        key.append("the answer key is only a suggestion; the content reviewer must confirm it")
    if (
        c.item_type is ItemType.SPR
        and c.answer_source is AnswerSource.REVIEWER
        and not (c.solution or "").strip()
    ):
        key.append(
            "a reviewer-supplied answer to a student-produced-response item needs a solution"
        )
    return key, other


class BankService:
    def __init__(self, uow: BankUnitOfWork, clock: Clock, ids: IdFactory) -> None:
        self._uow = uow
        self._clock = clock
        self._ids = ids

    # ---- Reads ---------------------------------------------------------------------------

    async def list_items(self, actor: PlatformActor, q: ItemQuery) -> Sequence[BankItem]:
        actor.require(Permission.BANK_AUTHOR)
        org = self._org(actor)
        q = replace(q, limit=max(1, min(q.limit, MAX_LIST)))

        async def read(tx: BankTx) -> Sequence[BankItem]:
            return await tx.items.query(org, q)

        return await self._uow.transaction(read)

    async def get_item(self, actor: PlatformActor, item_id: str) -> ItemDetail:
        actor.require(Permission.BANK_AUTHOR)
        org = self._org(actor)

        async def read(tx: BankTx) -> ItemDetail:
            item = await self._own(tx, org, item_id)
            versions = await tx.items.list_versions(org, item_id)
            current = next(v for v in versions if v.number == item.current_version)
            return ItemDetail(item=item, current=current, versions=versions)

        return await self._uow.transaction(read)

    async def get_passage(self, actor: PlatformActor, passage_id: str) -> BankPassage:
        actor.require(Permission.BANK_AUTHOR)
        org = self._org(actor)

        async def read(tx: BankTx) -> BankPassage:
            passage = await tx.passages.get(org, passage_id)
            if passage is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Passage not found.")
            return passage

        return await self._uow.transaction(read)

    # ---- Author commands --------------------------------------------------------------------

    async def create_passage(
        self,
        actor: PlatformActor,
        title: str,
        text: str,
        provenance: Provenance,
        cmd: CommandKey,
        flags: Sequence[str] = (),
    ) -> Outcome[BankPassage]:
        """A shared passage items can reference (`passageId`). Idempotent per key."""
        actor.require(Permission.BANK_AUTHOR)
        org = self._org(actor)
        if not text.strip():
            raise _invalid("A passage needs text.")
        if len(text) > MAX_PASSAGE_CHARS:
            raise _invalid(f"A passage is limited to {MAX_PASSAGE_CHARS} characters.")

        async def write(tx: BankTx) -> Outcome[BankPassage]:
            replay = await self._replay(tx, actor, cmd)
            if replay is not None:
                existing = await tx.passages.get(org, replay.resource_id)
                if existing is None:  # pragma: no cover - passages are never deleted
                    raise DomainError(ErrorCode.NOT_FOUND, "Passage not found.")
                return Outcome(value=existing, replayed=True, created=True)
            now = self._clock.now()
            passage = BankPassage(
                passage_id=self._ids.new("bkp"),
                org_id=org,
                title=title,
                text=text,
                provenance=provenance,
                created_by=actor.actor_id,
                created_at=now,
                flags=tuple(flags),
            )
            tx.passages.save(passage)
            self._remember(tx, actor, cmd, passage.passage_id, 201, now, PASSAGE_RESOURCE)
            return Outcome(value=passage, created=True)

        return await self._uow.transaction(write)

    async def create(
        self,
        actor: PlatformActor,
        inp: CreateItemInput,
        cmd: CommandKey,
        *,
        initial_state: BankItemState = BankItemState.DRAFT,
    ) -> Outcome[ItemDetail]:
        """A new item with version 1. Hand-made items start as `draft`; the import path
        (Step 39) creates `extracted` items through the same method."""
        actor.require(Permission.BANK_AUTHOR)
        if initial_state not in (BankItemState.DRAFT, BankItemState.EXTRACTED):
            raise ValueError("new items start as draft or extracted")
        org = self._org(actor)
        self._check_author_key(actor, inp.content)
        check_content(inp.content)

        async def write(tx: BankTx) -> Outcome[ItemDetail]:
            replay = await self._replay(tx, actor, cmd)
            if replay is not None:
                return Outcome(
                    value=await self._detail(tx, org, replay.resource_id),
                    replayed=True,
                    created=replay.response_status == 201,
                )
            await self._check_passage(tx, org, inp.content.passage_id)
            now = self._clock.now()
            item_id = self._ids.new("bki")
            version = BankItemVersion(
                item_id=item_id,
                number=1,
                state=initial_state,
                content=inp.content,
                provenance=inp.provenance or Provenance(kind=ProvenanceKind.AUTHOR),
                created_by=actor.actor_id,
                created_at=now,
                updated_at=now,
            )
            item = BankItem(
                item_id=item_id,
                org_id=org,
                course_id=inp.course_id,
                state=initial_state,
                current_version=1,
                approved_version=None,
                revision=1,
                tags=tuple(inp.tags),
                flags=tuple(inp.content.flags),
                content_hash=content_hash(inp.content.stem, inp.content.choices),
                created_by=actor.actor_id,
                created_at=now,
                updated_at=now,
                history=(
                    ItemChange(
                        action="create",
                        version=1,
                        actor_id=actor.actor_id,
                        at=now,
                        to_state=initial_state,
                    ),
                ),
            )
            tx.items.save_version(org, version)
            tx.items.save(item)
            self._remember(tx, actor, cmd, item_id, 201, now)
            return Outcome(value=ItemDetail(item=item, current=version), created=True)

        return await self._uow.transaction(write)

    async def edit(
        self,
        actor: PlatformActor,
        item_id: str,
        expected_revision: int,
        changes: Mapping[str, Any],
        cmd: CommandKey,
    ) -> Outcome[ItemDetail]:
        """Apply field changes. `extracted`/`draft` items change in place; an item in review
        changes in place only for a content reviewer; an approved or rejected item gets a new
        draft version. Retired and discarded items cannot change."""
        actor.require(Permission.BANK_AUTHOR)
        org = self._org(actor)
        unknown = set(changes) - CONTENT_FIELDS - HEADER_FIELDS
        if unknown:
            raise _invalid("Unknown fields: " + ", ".join(sorted(unknown)))
        if not changes:
            raise _invalid("No changes given.")

        async def write(tx: BankTx) -> Outcome[ItemDetail]:
            replay = await self._replay(tx, actor, cmd)
            if replay is not None:
                return Outcome(
                    value=await self._detail(tx, org, replay.resource_id),
                    replayed=True,
                    created=False,
                )
            item = await self._own(tx, org, item_id)
            if item.revision != expected_revision:
                raise DomainError(
                    ErrorCode.VERSION_CONFLICT,
                    f"The item changed (revision {item.revision}); reload and try again.",
                )
            current = await self._version(tx, org, item, item.current_version)
            content_changes = {k: v for k, v in changes.items() if k in CONTENT_FIELDS}
            content = replace(current.content, **content_changes)
            if "answer" in content_changes and "answer_source" not in content_changes:
                content = replace(
                    content,
                    answer_source=None if content.answer is None else current.content.answer_source,
                )
            self._check_author_key(actor, content, previous=current.content)
            check_content(content)
            if content.passage_id != current.content.passage_id:
                await self._check_passage(tx, org, content.passage_id)
            now = self._clock.now()

            if item.state in EDITABLE_IN_PLACE or (
                item.state is BankItemState.IN_REVIEW and actor.can(Permission.BANK_REVIEW)
            ):
                version = replace(current, content=content, updated_at=now)
                state = item.state
            elif item.state in EDIT_OPENS_VERSION:
                version = BankItemVersion(
                    item_id=item_id,
                    number=item.current_version + 1,
                    state=BankItemState.DRAFT,
                    content=content,
                    provenance=current.provenance,
                    created_by=actor.actor_id,
                    created_at=now,
                    updated_at=now,
                )
                state = BankItemState.DRAFT
            elif item.state is BankItemState.IN_REVIEW:
                raise DomainError(
                    ErrorCode.INVALID_STATE_TRANSITION,
                    "The item is in review; only the content reviewer can change it now.",
                )
            else:
                raise DomainError(
                    ErrorCode.INVALID_STATE_TRANSITION, f"A {item.state.value} item cannot change."
                )
            item = replace(
                item,
                course_id=changes.get("course_id", item.course_id),
                tags=tuple(changes.get("tags", item.tags)),
                flags=tuple(content.flags),
                content_hash=content_hash(content.stem, content.choices),
                state=state,
                current_version=version.number,
                revision=item.revision + 1,
                updated_at=now,
                history=(
                    *item.history,
                    ItemChange(
                        action="edit",
                        version=version.number,
                        actor_id=actor.actor_id,
                        at=now,
                        from_state=item.state,
                        to_state=state,
                        notes=", ".join(sorted(changes)),
                    ),
                ),
            )
            tx.items.save_version(org, version)
            tx.items.save(item)
            self._remember(tx, actor, cmd, item_id, 200, now)
            return Outcome(value=ItemDetail(item=item, current=version), created=False)

        return await self._uow.transaction(write)

    async def confirm(
        self, actor: PlatformActor, item_id: str, cmd: CommandKey
    ) -> Outcome[ItemDetail]:
        """`extracted` → `draft`: an author has opened and accepted the extracted item."""
        actor.require(Permission.BANK_AUTHOR)
        return await self._move(
            actor, item_id, cmd, "confirm", BankItemState.DRAFT, expect=BankItemState.EXTRACTED
        )

    async def submit(
        self, actor: PlatformActor, item_id: str, cmd: CommandKey
    ) -> Outcome[ItemDetail]:
        """`draft` → `in_review`. Records who submitted the version."""
        actor.require(Permission.BANK_AUTHOR)

        def stamp(v: BankItemVersion, now: datetime) -> BankItemVersion:
            if not v.content.stem.strip():
                raise _invalid("An item needs a stem before it can be submitted.")
            return replace(v, submitted_by=actor.actor_id, submitted_at=now)

        return await self._move(
            actor,
            item_id,
            cmd,
            "submit",
            BankItemState.IN_REVIEW,
            expect=BankItemState.DRAFT,
            update=stamp,
        )

    async def discard(
        self, actor: PlatformActor, item_id: str, cmd: CommandKey, notes: str = ""
    ) -> Outcome[ItemDetail]:
        """Drop an item that was never approved."""
        actor.require(Permission.BANK_AUTHOR)
        return await self._move(
            actor,
            item_id,
            cmd,
            "discard",
            BankItemState.DISCARDED,
            notes=notes,
            never_approved=True,
        )

    # ---- Content reviewer commands ----------------------------------------------------------

    async def set_key(
        self,
        actor: PlatformActor,
        item_id: str,
        answer: str,
        solution: str | None,
        cmd: CommandKey,
        *,
        expected_revision: int | None = None,
    ) -> Outcome[ItemDetail]:
        """Set the final key (`answerSource: reviewer`) and solution of a draft or in-review
        version. This is also how a reviewer confirms an agent-suggested key or replaces a
        disputed source key (record the reason in the approval notes)."""
        actor.require(Permission.BANK_REVIEW)

        def apply(v: BankItemVersion, now: datetime) -> BankItemVersion:
            content = replace(
                v.content,
                answer=answer,
                answer_source=AnswerSource.REVIEWER,
                solution=solution if solution is not None else v.content.solution,
            )
            check_content(content)
            return replace(v, content=content, updated_at=now)

        return await self._move(
            actor,
            item_id,
            cmd,
            "key",
            None,
            update=apply,
            allowed_from=(BankItemState.DRAFT, BankItemState.IN_REVIEW),
            expected_revision=expected_revision,
        )

    async def approve(
        self, actor: PlatformActor, item_id: str, notes: str, cmd: CommandKey
    ) -> Outcome[ItemDetail]:
        actor.require(Permission.BANK_REVIEW)

        def decide(v: BankItemVersion, now: datetime) -> BankItemVersion:
            missing_key, other = approval_problems(v.content)
            if missing_key:
                raise DomainError(
                    ErrorCode.ITEM_KEY_REQUIRED, "Cannot approve: " + "; ".join(missing_key)
                )
            if other:
                raise _invalid("Cannot approve: " + "; ".join(other))
            return replace(
                v,
                review=ItemReview(
                    reviewer_id=actor.actor_id,
                    decision=BankItemState.APPROVED,
                    decided_at=now,
                    notes=notes,
                ),
            )

        return await self._move(
            actor,
            item_id,
            cmd,
            "approve",
            BankItemState.APPROVED,
            expect=BankItemState.IN_REVIEW,
            update=decide,
            notes=notes,
        )

    async def reject(
        self, actor: PlatformActor, item_id: str, notes: str, cmd: CommandKey
    ) -> Outcome[ItemDetail]:
        actor.require(Permission.BANK_REVIEW)
        if not notes.strip():
            raise _invalid("Rejection notes are required.")

        def decide(v: BankItemVersion, now: datetime) -> BankItemVersion:
            return replace(
                v,
                review=ItemReview(
                    reviewer_id=actor.actor_id,
                    decision=BankItemState.REJECTED,
                    decided_at=now,
                    notes=notes,
                ),
            )

        return await self._move(
            actor,
            item_id,
            cmd,
            "reject",
            BankItemState.REJECTED,
            expect=BankItemState.IN_REVIEW,
            update=decide,
            notes=notes,
        )

    async def retire(
        self, actor: PlatformActor, item_id: str, notes: str, cmd: CommandKey
    ) -> Outcome[ItemDetail]:
        """An approved item stops being selectable. Packages already built keep their copy."""
        actor.require(Permission.BANK_REVIEW)
        return await self._move(
            actor,
            item_id,
            cmd,
            "retire",
            BankItemState.RETIRED,
            expect=BankItemState.APPROVED,
            notes=notes,
        )

    # ---- Internals ---------------------------------------------------------------------------

    async def _move(
        self,
        actor: PlatformActor,
        item_id: str,
        cmd: CommandKey,
        action: str,
        to: BankItemState | None,
        *,
        expect: BankItemState | None = None,
        allowed_from: Sequence[BankItemState] = (),
        update: Any = None,
        notes: str = "",
        never_approved: bool = False,
        expected_revision: int | None = None,
    ) -> Outcome[ItemDetail]:
        """One state change (or, with `to=None`, an in-place update) of the current version."""
        org = self._org(actor)

        async def write(tx: BankTx) -> Outcome[ItemDetail]:
            replay = await self._replay(tx, actor, cmd)
            if replay is not None:
                return Outcome(
                    value=await self._detail(tx, org, replay.resource_id),
                    replayed=True,
                    created=False,
                )
            item = await self._own(tx, org, item_id)
            if expected_revision is not None and item.revision != expected_revision:
                raise DomainError(
                    ErrorCode.VERSION_CONFLICT,
                    f"The item changed (revision {item.revision}); reload and try again.",
                )
            if expect is not None and item.state is not expect:
                raise self._bad_state(item, action)
            if allowed_from and item.state not in allowed_from:
                raise self._bad_state(item, action)
            if to is not None and to not in ITEM_TRANSITIONS[item.state]:
                raise self._bad_state(item, action)
            if never_approved and item.approved_version is not None:
                raise DomainError(
                    ErrorCode.INVALID_STATE_TRANSITION,
                    "This item was approved before; retire it instead of discarding it.",
                )
            now = self._clock.now()
            version = await self._version(tx, org, item, item.current_version)
            if update is not None:
                version = update(version, now)
            new_state = to or item.state
            version = replace(version, state=new_state, updated_at=now)
            approved = item.approved_version
            if new_state is BankItemState.APPROVED:
                approved = version.number
            item = replace(
                item,
                state=new_state,
                approved_version=approved,
                flags=tuple(version.content.flags),
                revision=item.revision + 1,
                updated_at=now,
                history=(
                    *item.history,
                    ItemChange(
                        action=action,
                        version=version.number,
                        actor_id=actor.actor_id,
                        at=now,
                        from_state=item.state,
                        to_state=new_state,
                        notes=notes,
                    ),
                ),
            )
            tx.items.save_version(org, version)
            tx.items.save(item)
            self._remember(tx, actor, cmd, item_id, 200, now)
            return Outcome(value=ItemDetail(item=item, current=version), created=False)

        return await self._uow.transaction(write)

    @staticmethod
    def _bad_state(item: BankItem, action: str) -> DomainError:
        return DomainError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Cannot {action} an item that is {item.state.value}.",
        )

    @staticmethod
    def _check_author_key(
        actor: PlatformActor, content: ItemContent, previous: ItemContent | None = None
    ) -> None:
        """Only a content reviewer records a key as `reviewer`; authors record keys found in
        the material or suggestions. Authors also cannot silently change a reviewer key."""
        if actor.can(Permission.BANK_REVIEW):
            return
        if content.answer_source is AnswerSource.REVIEWER and not (
            previous is not None
            and previous.answer_source is AnswerSource.REVIEWER
            and previous.answer == content.answer
        ):
            raise DomainError(
                ErrorCode.FORBIDDEN, "Only a content reviewer can set a reviewer answer key."
            )
        if content.answer_source is not None and content.answer_source not in (
            *AUTHOR_ANSWER_SOURCES,
            AnswerSource.REVIEWER,
        ):  # pragma: no cover - enum is closed
            raise _invalid("Unknown answerSource.")

    @staticmethod
    async def _check_passage(tx: BankTx, org: str, passage_id: str | None) -> None:
        if passage_id is not None and await tx.passages.get(org, passage_id) is None:
            raise _invalid(f"passageId {passage_id} is not a passage of this organization.")

    @staticmethod
    def _org(actor: PlatformActor) -> str:
        if actor.org_id is None:  # platform reviewers and admins have no bank
            raise DomainError(ErrorCode.FORBIDDEN, "This account has no organization bank.")
        return actor.org_id

    @staticmethod
    async def _own(tx: BankTx, org: str, item_id: str) -> BankItem:
        item = await tx.items.get(org, item_id)
        if item is None:
            raise _not_found()
        return item

    @staticmethod
    async def _version(tx: BankTx, org: str, item: BankItem, number: int) -> BankItemVersion:
        v = await tx.items.get_version(org, item.item_id, number)
        if v is None:  # pragma: no cover - versions are written with their header
            raise _not_found()
        return v

    async def _detail(self, tx: BankTx, org: str, item_id: str) -> ItemDetail:
        item = await self._own(tx, org, item_id)
        return ItemDetail(
            item=item, current=await self._version(tx, org, item, item.current_version)
        )

    @staticmethod
    async def _replay(
        tx: BankTx, actor: PlatformActor, cmd: CommandKey
    ) -> IdempotencyRecord | None:
        record = await tx.idempotency.get(actor.actor_id, cmd.key_hash(actor))
        if record is None:
            return None
        if record.scope != cmd.scope or record.request_digest != cmd.request_digest:
            raise DomainError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "This Idempotency-Key was already used with a different request.",
            )
        return record

    @staticmethod
    def _remember(
        tx: BankTx,
        actor: PlatformActor,
        cmd: CommandKey,
        item_id: str,
        status: int,
        now: datetime,
        resource_type: str = ITEM_RESOURCE,
    ) -> None:
        tx.idempotency.save(
            actor.actor_id,
            IdempotencyRecord(
                key_hash=cmd.key_hash(actor),
                scope=cmd.scope,
                request_digest=cmd.request_digest,
                resource_type=resource_type,
                resource_id=item_id,
                response_status=status,
                created_at=now,
            ),
        )
