"""Quick entry into the question bank (Step 39A, QUESTION_BANK.md §7.1).

- `preview` splits pasted text or CSV deterministically and marks duplicates; it never writes.
- `import_batch` writes a batch the author reviewed — up to 100 questions and their passages —
  as `draft` items in one transaction, with the batch settings applied. A question whose
  content hash matches an item already in the organization's bank, or an earlier question of
  the batch, is skipped unless the author keeps duplicates. The batch is recorded as an
  ImportJob (`kind: batch`), which is also what an Idempotency-Key replay returns.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from app.domain.bank_service import DIFFICULTIES, check_content
from app.domain.commands import CommandKey, Outcome
from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.bank import BankTx, BankUnitOfWork, ItemQuery
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.question_splitter import ParseResult, parse_csv, parse_text
from app.domain.types.actor import Permission, PlatformActor
from app.domain.types.bank import (
    AUTHOR_ANSWER_SOURCES,
    CHOICE_KEYS,
    MAX_PASSAGE_CHARS,
    AnswerSource,
    BankItem,
    BankItemState,
    BankItemVersion,
    BankPassage,
    ImportJob,
    ImportKind,
    ImportStatus,
    ItemChange,
    ItemContent,
    ItemType,
    Provenance,
    ProvenanceKind,
    content_hash,
)
from app.domain.types.common import IdempotencyRecord

MAX_BATCH_QUESTIONS = 100
MAX_BATCH_PASSAGES = 20
IMPORT_RESOURCE = "bank_import"
KEY_ORIGINS = frozenset({AnswerSource.SOURCE_KEY, AnswerSource.COMPILED_KEY})


@dataclass(frozen=True, slots=True, kw_only=True)
class Preview:
    result: ParseResult
    duplicates: Mapping[int, str]  # question number → existing itemId or "question N"


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchPassage:
    ref: str
    title: str
    text: str


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchQuestion:
    number: int
    content: ItemContent  # answer_source is filled from the batch key origin when missing
    passage_ref: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class BatchSettings:
    course_id: str | None = None
    section: str | None = None
    skill_ids: Sequence[str] = ()
    difficulty: str | None = None
    key_origin: AnswerSource = AnswerSource.SOURCE_KEY
    source_title: str | None = None
    source_license: str | None = None  # recorded, not enforced
    tags: Sequence[str] = field(default_factory=tuple)


def _invalid(message: str) -> DomainError:
    return DomainError(ErrorCode.VALIDATION_FAILED, message)


def _org(actor: PlatformActor) -> str:
    if actor.org_id is None:  # pragma: no cover - membership always carries an org for authors
        raise DomainError(ErrorCode.FORBIDDEN, "Not a member of an author organization.")
    return actor.org_id


async def _existing(tx: BankTx, org: str, hashes: Sequence[str]) -> dict[str, str]:
    """content hash → itemId of an item already in the organization's bank."""
    found: dict[str, str] = {}
    unique = sorted(set(hashes))
    for i in range(0, len(unique), 30):
        for item in await tx.items.query(
            org, ItemQuery(content_hashes=unique[i : i + 30], limit=200)
        ):
            if item.content_hash and item.content_hash not in found:
                found[item.content_hash] = item.item_id
    return found


class BankEntryService:
    def __init__(self, uow: BankUnitOfWork, clock: Clock, ids: IdFactory) -> None:
        self._uow = uow
        self._clock = clock
        self._ids = ids

    async def preview(self, actor: PlatformActor, fmt: str, text: str) -> Preview:
        actor.require(Permission.BANK_AUTHOR)
        org = _org(actor)
        if fmt not in ("text", "csv"):
            raise _invalid("format must be text or csv.")
        result = parse_csv(text) if fmt == "csv" else parse_text(text)
        hashes = {q.number: content_hash(q.stem, q.choices) for q in result.questions}

        async def read(tx: BankTx) -> dict[str, str]:
            return await _existing(tx, org, list(hashes.values()))

        existing = await self._uow.transaction(read)
        duplicates: dict[int, str] = {}
        seen: dict[str, int] = {}
        for q in result.questions:
            h = hashes[q.number]
            if h in existing:
                duplicates[q.number] = existing[h]
            elif h in seen:
                duplicates[q.number] = f"question {seen[h]}"
            seen.setdefault(h, q.number)
        return Preview(result=result, duplicates=duplicates)

    async def import_batch(
        self,
        actor: PlatformActor,
        questions: Sequence[BatchQuestion],
        passages: Sequence[BatchPassage],
        settings: BatchSettings,
        cmd: CommandKey,
        *,
        keep_duplicates: bool = False,
    ) -> Outcome[ImportJob]:
        actor.require(Permission.BANK_AUTHOR)
        org = _org(actor)
        if not questions:
            raise _invalid("The batch has no questions.")
        if len(questions) > MAX_BATCH_QUESTIONS:
            raise _invalid(f"A batch holds at most {MAX_BATCH_QUESTIONS} questions; split it.")
        if len(passages) > MAX_BATCH_PASSAGES:
            raise _invalid(f"A batch holds at most {MAX_BATCH_PASSAGES} passages; split it.")
        if settings.key_origin not in KEY_ORIGINS:
            raise _invalid("keyOrigin must be source-key or compiled-key.")
        if settings.difficulty is not None and settings.difficulty not in DIFFICULTIES:
            raise _invalid("difficulty must be easy, medium or hard.")
        by_ref = {p.ref: p for p in passages}
        if len(by_ref) != len(passages):
            raise _invalid("Passage refs must be unique.")
        problems: list[str] = []
        prepared: list[tuple[BatchQuestion, ItemContent]] = []
        numbers: set[int] = set()
        for q in questions:
            content = self._content(q, settings)
            try:
                check_content(content)
            except DomainError as exc:
                problems.append(f"question {q.number}: {exc.message}")
            if (
                q.content.answer_source is not None
                and q.content.answer_source not in AUTHOR_ANSWER_SOURCES
            ):
                problems.append(
                    f"question {q.number}: only the content reviewer records reviewer keys"
                )
            if q.passage_ref is not None and q.content.passage_id is not None:
                problems.append(f"question {q.number}: give either a passage ref or a passageId")
            if q.passage_ref is not None and q.passage_ref not in by_ref:
                problems.append(
                    f"question {q.number}: passage “{q.passage_ref}” is not in the batch"
                )
            if q.number in numbers:
                problems.append(f"question {q.number} appears twice")
            numbers.add(q.number)
            prepared.append((q, content))
        for p in passages:
            if not p.text.strip():
                problems.append(f"passage “{p.ref}” has no text")
            if len(p.text) > MAX_PASSAGE_CHARS:
                problems.append(f"passage “{p.ref}” is longer than {MAX_PASSAGE_CHARS} characters")
        if problems:
            raise _invalid("The batch was not imported: " + "; ".join(problems))

        async def write(tx: BankTx) -> Outcome[ImportJob]:
            record = await tx.idempotency.get(actor.actor_id, cmd.key_hash(actor))
            if record is not None:
                if record.scope != cmd.scope or record.request_digest != cmd.request_digest:
                    raise DomainError(
                        ErrorCode.IDEMPOTENCY_CONFLICT,
                        "This Idempotency-Key was already used with a different request.",
                    )
                job = await tx.imports.get(org, record.resource_id)
                if job is None:  # pragma: no cover - jobs are never deleted
                    raise DomainError(ErrorCode.NOT_FOUND, "Import not found.")
                return Outcome(value=job, replayed=True, created=True)

            for pid in sorted({c.passage_id for _, c in prepared if c.passage_id}):
                if await tx.passages.get(org, pid) is None:
                    raise _invalid(f"Passage {pid} is not in your organization's bank.")
            now = self._clock.now()
            job_id = self._ids.new("imp")
            existing = await _existing(
                tx, org, [content_hash(c.stem, c.choices) for _, c in prepared]
            )
            seen: dict[str, int] = {}
            keep: list[tuple[BatchQuestion, ItemContent]] = []
            skipped: list[str] = []
            for q, c in prepared:
                h = content_hash(c.stem, c.choices)
                dup = existing.get(h) or (f"question {seen[h]}" if h in seen else None)
                seen.setdefault(h, q.number)
                if dup and not keep_duplicates:
                    skipped.append(f"question {q.number}: duplicate of {dup}")
                    continue
                if dup:
                    c = replace(c, flags=(*c.flags, f"duplicate-of:{dup}"))
                keep.append((q, c))

            passage_ids: dict[str, str] = {}
            for ref in sorted({q.passage_ref for q, _ in keep if q.passage_ref}):
                p = by_ref[ref]
                passage = BankPassage(
                    passage_id=self._ids.new("bkp"),
                    org_id=org,
                    title=p.title or "Passage",
                    text=p.text,
                    provenance=Provenance(
                        kind=ProvenanceKind.AUTHOR,
                        import_job_id=job_id,
                        reference=settings.source_title,
                    ),
                    created_by=actor.actor_id,
                    created_at=now,
                )
                tx.passages.save(passage)
                passage_ids[ref] = passage.passage_id

            item_ids: list[str] = []
            for q, c in keep:
                if q.passage_ref:
                    c = replace(c, passage_id=passage_ids[q.passage_ref])
                item_id = self._ids.new("bki")
                version = BankItemVersion(
                    item_id=item_id,
                    number=1,
                    state=BankItemState.DRAFT,
                    content=c,
                    provenance=Provenance(
                        kind=ProvenanceKind.AUTHOR,
                        import_job_id=job_id,
                        region=f"question {q.number}",
                        reference=settings.source_title,
                    ),
                    created_by=actor.actor_id,
                    created_at=now,
                    updated_at=now,
                )
                tx.items.save_version(org, version)
                tx.items.save(
                    BankItem(
                        item_id=item_id,
                        org_id=org,
                        course_id=settings.course_id,
                        state=BankItemState.DRAFT,
                        current_version=1,
                        approved_version=None,
                        revision=1,
                        tags=tuple(settings.tags),
                        flags=tuple(c.flags),
                        content_hash=content_hash(c.stem, c.choices),
                        created_by=actor.actor_id,
                        created_at=now,
                        updated_at=now,
                        history=(
                            ItemChange(
                                action="import",
                                version=1,
                                actor_id=actor.actor_id,
                                at=now,
                                to_state=BankItemState.DRAFT,
                                notes=f"batch {job_id}",
                            ),
                        ),
                    )
                )
                item_ids.append(item_id)

            job = ImportJob(
                job_id=job_id,
                org_id=org,
                kind=ImportKind.BATCH,
                source_ids=(),
                status=ImportStatus.SUCCEEDED,
                created_by=actor.actor_id,
                created_at=now,
                updated_at=now,
                course_hint=settings.course_id,
                item_count=len(item_ids),
                item_ids=tuple(item_ids),
                passage_ids=tuple(passage_ids.values()),
                skipped=tuple(skipped),
                source_title=settings.source_title,
            )
            tx.imports.save(job)
            tx.idempotency.save(
                actor.actor_id,
                IdempotencyRecord(
                    key_hash=cmd.key_hash(actor),
                    scope=cmd.scope,
                    request_digest=cmd.request_digest,
                    resource_type=IMPORT_RESOURCE,
                    resource_id=job_id,
                    response_status=201,
                    created_at=now,
                ),
            )
            return Outcome(value=job, created=True)

        return await self._uow.transaction(write)

    async def get_import(self, actor: PlatformActor, job_id: str) -> ImportJob:
        actor.require(Permission.BANK_AUTHOR)
        org = _org(actor)

        async def read(tx: BankTx) -> ImportJob:
            job = await tx.imports.get(org, job_id)
            if job is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Import not found.")
            return job

        return await self._uow.transaction(read)

    async def list_imports(self, actor: PlatformActor) -> Sequence[ImportJob]:
        actor.require(Permission.BANK_AUTHOR)
        org = _org(actor)

        async def read(tx: BankTx) -> Sequence[ImportJob]:
            return await tx.imports.list_for_org(org, 50)

        return await self._uow.transaction(read)

    @staticmethod
    def _content(q: BatchQuestion, s: BatchSettings) -> ItemContent:
        """Apply the batch settings where the question leaves a field empty, and flag
        what the reviewer will need to fix."""
        c = q.content
        flags = list(c.flags)
        if c.answer is None and "key-missing" not in flags:
            flags.append("key-missing")
        if c.item_type is ItemType.MC and sorted(c.choices or {}) != list(CHOICE_KEYS):
            flags.append("choices-incomplete")
        return replace(
            c,
            section=c.section or s.section,
            skill_ids=tuple(c.skill_ids) or tuple(s.skill_ids),
            difficulty=c.difficulty or s.difficulty,
            answer_source=(c.answer_source or s.key_origin) if c.answer else None,
            flags=tuple(dict.fromkeys(flags)),
        )
