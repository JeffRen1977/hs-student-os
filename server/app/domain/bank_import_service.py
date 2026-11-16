"""File import into the question bank (Step 39B, QUESTION_BANK.md §4.1-4.2, §7.2).

Sources and pages: an author registers a source (`pdf`, `image`, `text` or `link`) and
uploads its pages — page images rendered and downscaled in the browser, plus any text layer.
Links are fetched by the platform under the link guard. Pages freeze once a job reads them.

Jobs: `start_import` queues one task per page. `ImportProcessor` (local worker tick; Cloud
Scheduler when deployed) leases a job and works one page at a time:
1. read the page in a transaction;
2. outside any transaction: the deterministic splitter when the text layer parses cleanly,
   otherwise the `question-extraction` ability through the model gateway, charged to the
   organization's budget;
3. commit that page's extracted items, passages and progress in one transaction fenced by
   the lease token — a worker whose lease was taken over commits nothing.
Item ids derive from job + page + question number, so a retried page never duplicates.
After the last page, keys from answer-key pages are matched to the job's unkeyed questions by
number. Extracted items are proposals: an author must open and confirm each one.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from app.domain.commands import CommandKey, Outcome
from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.bank import (
    BankTx,
    BankUnitOfWork,
    ImportQueueReader,
    LinkFetcher,
)
from app.domain.ports.execution import ExecutionFailure, RetryableExecutionError
from app.domain.ports.llm import IMAGE_TOKENS, BudgetExceededError, LlmGateway
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.question_splitter import ProposedPassage, ProposedQuestion, parse_text
from app.domain.skills import question_extraction
from app.domain.types.actor import Permission, PlatformActor
from app.domain.types.bank import (
    MAX_PAGE_TEXT_CHARS,
    MAX_PASSAGE_CHARS,
    MAX_SOURCE_PAGES,
    AnswerSource,
    BankItem,
    BankItemState,
    BankItemVersion,
    BankPassage,
    BankSource,
    FigureMode,
    ImportJob,
    ImportKind,
    ImportLease,
    ImportPage,
    ImportStatus,
    ItemChange,
    ItemContent,
    ItemType,
    PageStatus,
    Provenance,
    ProvenanceKind,
    SourceKind,
    SourcePage,
    content_hash,
)
from app.domain.types.common import IdempotencyRecord
from app.domain.types.file import validate_image

logger = logging.getLogger(__name__)

SOURCE_RESOURCE = "bank_source"
IMPORT_RESOURCE = "bank_import"
MAX_JOB_PAGES = 200
PAGE_OUTPUT_ESTIMATE = 4_000  # tokens per page sent to the model (for the estimate shown)
KEY_ORIGINS = frozenset({AnswerSource.SOURCE_KEY, AnswerSource.COMPILED_KEY})
BUDGET_MESSAGE = (
    "The organization's model budget for imports is used up; the remaining pages were not "
    "read. Try again tomorrow or split the file."
)


def _invalid(message: str) -> DomainError:
    return DomainError(ErrorCode.VALIDATION_FAILED, message)


def _org(actor: PlatformActor) -> str:
    if actor.org_id is None:  # pragma: no cover - authors always have an organization
        raise DomainError(ErrorCode.FORBIDDEN, "Not a member of an author organization.")
    return actor.org_id


async def _replay(tx: BankTx, actor: PlatformActor, cmd: CommandKey) -> IdempotencyRecord | None:
    record = await tx.idempotency.get(actor.actor_id, cmd.key_hash(actor))
    if record is not None and (
        record.scope != cmd.scope or record.request_digest != cmd.request_digest
    ):
        raise DomainError(
            ErrorCode.IDEMPOTENCY_CONFLICT,
            "This Idempotency-Key was already used with a different request.",
        )
    return record


def _remember(
    tx: BankTx, actor: PlatformActor, cmd: CommandKey, kind: str, rid: str, now: datetime
) -> None:
    tx.idempotency.save(
        actor.actor_id,
        IdempotencyRecord(
            key_hash=cmd.key_hash(actor),
            scope=cmd.scope,
            request_digest=cmd.request_digest,
            resource_type=kind,
            resource_id=rid,
            response_status=201,
            created_at=now,
        ),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class NewSource:
    kind: SourceKind
    title: str
    license: str | None = None
    url: str | None = None
    text: str | None = None
    page_count: int | None = None


class ImportService:
    def __init__(
        self,
        uow: BankUnitOfWork,
        clock: Clock,
        ids: IdFactory,
        links: LinkFetcher | None,
        *,
        model_available: bool,
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._ids = ids
        self._links = links
        self._model = model_available

    # ---- Sources and pages ---------------------------------------------------------------

    async def create_source(
        self, actor: PlatformActor, new: NewSource, cmd: CommandKey
    ) -> Outcome[BankSource]:
        actor.require(Permission.BANK_AUTHOR)
        org = _org(actor)
        if not new.title.strip():
            raise _invalid("Give the source a title.")
        text: str | None = None
        url: str | None = None
        pages = 1
        if new.kind in (SourceKind.PDF, SourceKind.IMAGE):
            if new.page_count is None or not 1 <= new.page_count <= MAX_SOURCE_PAGES:
                raise _invalid(f"pageCount must be 1-{MAX_SOURCE_PAGES}.")
            pages = new.page_count
        elif new.kind is SourceKind.TEXT:
            text = (new.text or "").strip()
            if not text:
                raise _invalid("A text source needs text.")
            if len(text) > MAX_PAGE_TEXT_CHARS:
                raise _invalid(f"Text is limited to {MAX_PAGE_TEXT_CHARS} characters; split it.")
        elif new.kind is SourceKind.LINK:
            if self._links is None:
                raise DomainError(
                    ErrorCode.IMPORT_SOURCE_REJECTED, "Links cannot be fetched in this environment."
                )
            fetched = await self._links.fetch(new.url or "")  # outside any transaction
            url, text = fetched.url, fetched.text[:MAX_PAGE_TEXT_CHARS]
            if not text.strip():
                raise DomainError(
                    ErrorCode.IMPORT_SOURCE_REJECTED, "The page has no readable text."
                )
        else:
            raise _invalid("kind must be pdf, image, text or link.")

        async def write(tx: BankTx) -> Outcome[BankSource]:
            record = await _replay(tx, actor, cmd)
            if record is not None:
                existing = await tx.sources.get(org, record.resource_id)
                if existing is None:  # pragma: no cover
                    raise DomainError(ErrorCode.NOT_FOUND, "Source not found.")
                return Outcome(value=existing, replayed=True, created=True)
            now = self._clock.now()
            source = BankSource(
                source_id=self._ids.new("src"),
                org_id=org,
                kind=new.kind,
                title=new.title.strip(),
                uploaded_by=actor.actor_id,
                created_at=now,
                url=url,
                fetched_at=now if url else None,
                content_hash=hashlib.sha256(text.encode()).hexdigest() if text else None,
                page_count=pages,
                license=new.license,
            )
            tx.sources.save(source)
            if text is not None:
                tx.sources.save_page(
                    org, SourcePage(source_id=source.source_id, number=1, text=text)
                )
            _remember(tx, actor, cmd, SOURCE_RESOURCE, source.source_id, now)
            return Outcome(value=source, created=True)

        return await self._uow.transaction(write)

    async def put_page(
        self,
        actor: PlatformActor,
        source_id: str,
        number: int,
        *,
        media_type: str | None,
        data_base64: str | None,
        text: str | None,
    ) -> SourcePage:
        """Upload (or replace) one page. A PUT is naturally idempotent."""
        actor.require(Permission.BANK_AUTHOR)
        org = _org(actor)
        size = 0
        if data_base64:
            size = validate_image(media_type or "", data_base64)
        if text is not None and len(text) > MAX_PAGE_TEXT_CHARS:
            raise _invalid(f"Page text is limited to {MAX_PAGE_TEXT_CHARS} characters.")
        if not data_base64 and not (text or "").strip():
            raise _invalid("A page needs an image or text.")

        async def write(tx: BankTx) -> SourcePage:
            source = await self._source(tx, org, source_id)
            if source.kind not in (SourceKind.PDF, SourceKind.IMAGE):
                raise _invalid("Only pdf and image sources take page uploads.")
            if not 1 <= number <= (source.page_count or 0):
                raise _invalid(f"Page {number} is outside 1-{source.page_count}.")
            if source.used_by_job:
                raise DomainError(
                    ErrorCode.INVALID_STATE_TRANSITION,
                    "This source was already imported; its pages cannot change.",
                )
            page = SourcePage(
                source_id=source_id,
                number=number,
                media_type=media_type if data_base64 else None,
                data_base64=data_base64 or None,
                text=text or None,
                size_bytes=size,
            )
            tx.sources.save_page(org, page)
            return page

        return await self._uow.transaction(write)

    async def get_page(self, actor: PlatformActor, source_id: str, number: int) -> SourcePage:
        actor.require(Permission.BANK_AUTHOR)
        org = _org(actor)

        async def read(tx: BankTx) -> SourcePage:
            await self._source(tx, org, source_id)
            page = await tx.sources.get_page(org, source_id, number)
            if page is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Page not found.")
            return page

        return await self._uow.transaction(read)

    async def get_source(self, actor: PlatformActor, source_id: str) -> tuple[BankSource, int]:
        """The source and how many of its pages are uploaded."""
        actor.require(Permission.BANK_AUTHOR)
        org = _org(actor)

        async def read(tx: BankTx) -> tuple[BankSource, int]:
            source = await self._source(tx, org, source_id)
            return source, len(await tx.sources.page_numbers(org, source_id))

        return await self._uow.transaction(read)

    # ---- Jobs ---------------------------------------------------------------------------------

    async def start_import(
        self,
        actor: PlatformActor,
        source_ids: Sequence[str],
        cmd: CommandKey,
        *,
        course_id: str | None = None,
        key_origin: AnswerSource = AnswerSource.SOURCE_KEY,
    ) -> Outcome[ImportJob]:
        actor.require(Permission.BANK_AUTHOR)
        org = _org(actor)
        if not source_ids or len(set(source_ids)) != len(source_ids):
            raise _invalid("Name each source once.")
        if key_origin not in KEY_ORIGINS:
            raise _invalid("keyOrigin must be source-key or compiled-key.")

        async def write(tx: BankTx) -> Outcome[ImportJob]:
            record = await _replay(tx, actor, cmd)
            if record is not None:
                job = await tx.imports.get(org, record.resource_id)
                if job is None:  # pragma: no cover
                    raise DomainError(ErrorCode.NOT_FOUND, "Import not found.")
                return Outcome(value=job, replayed=True, created=True)
            now = self._clock.now()
            job_id = self._ids.new("imp")
            pages: list[ImportPage] = []
            estimate = 0
            sources: list[BankSource] = []
            for sid in source_ids:
                source = await self._source(tx, org, sid)
                if source.used_by_job:
                    raise DomainError(
                        ErrorCode.INVALID_STATE_TRANSITION,
                        f"“{source.title}” was already imported.",
                    )
                numbers = list(await tx.sources.page_numbers(org, sid))
                expected = list(range(1, (source.page_count or 0) + 1))
                if numbers != expected:
                    missing = sorted(set(expected) - set(numbers))
                    raise _invalid(f"“{source.title}”: pages {missing[:10]} are not uploaded yet.")
                for n in numbers:
                    pages.append(ImportPage(source_id=sid, page=n))
                    if source.kind in (SourceKind.PDF, SourceKind.IMAGE):
                        estimate += IMAGE_TOKENS + PAGE_OUTPUT_ESTIMATE
                sources.append(source)
            if len(pages) > MAX_JOB_PAGES:
                raise _invalid(f"A job reads at most {MAX_JOB_PAGES} pages; split the sources.")
            for source in sources:
                tx.sources.save(replace(source, used_by_job=job_id))
            job = ImportJob(
                job_id=job_id,
                org_id=org,
                kind=ImportKind.FILES,
                source_ids=tuple(source_ids),
                status=ImportStatus.QUEUED,
                created_by=actor.actor_id,
                created_at=now,
                updated_at=now,
                course_hint=course_id,
                source_title=", ".join(s.title for s in sources)[:200],
                pages=tuple(pages),
                key_origin=key_origin,
                estimate_tokens=estimate if self._model else 0,
            )
            tx.imports.save(job)
            _remember(tx, actor, cmd, IMPORT_RESOURCE, job_id, now)
            return Outcome(value=job, created=True)

        return await self._uow.transaction(write)

    @staticmethod
    async def _source(tx: BankTx, org: str, source_id: str) -> BankSource:
        source = await tx.sources.get(org, source_id)
        if source is None:
            raise DomainError(ErrorCode.NOT_FOUND, "Source not found.")
        return source


# ---- Worker side ----------------------------------------------------------------------------


class StaleLease(Exception):
    """Another worker took the job over; this one stops without writing."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PageResult:
    method: str  # text-layer | vision
    questions: Sequence[ProposedQuestion] = ()
    flags: Mapping[int, Sequence[str]] = field(default_factory=dict)
    passages: Sequence[ProposedPassage] = ()
    answer_key: Mapping[int, str] = field(default_factory=dict)
    tokens: int = 0
    error: str | None = None


def _number(item_region: str | None) -> int | None:
    if item_region and item_region.startswith("question "):
        tail = item_region.removeprefix("question ")
        return int(tail) if tail.isdigit() else None
    return None


class ImportProcessor:
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

    async def process_due(self, limit: int = 3) -> int:
        """Run due jobs to completion (or until their lease is lost). Returns jobs touched."""
        done = 0
        for org, job_id in await self._queue.due_jobs(self._clock.now(), limit):
            try:
                await self.run_job(org, job_id)
                done += 1
            except StaleLease:
                logger.info("import_lease_lost", extra={"jobId": job_id})
        return done

    async def run_job(self, org: str, job_id: str) -> None:
        token = self._ids.new("lease")
        job = await self._claim(org, job_id, token)
        if job is None:
            return
        for index, task in enumerate(job.pages):
            if task.status is not PageStatus.PENDING:
                continue
            page = await self._read_page(org, task.source_id, task.page)
            try:
                result = await self._extract(org, job, page)
            except BudgetExceededError:
                await self._fail(org, job_id, token, BUDGET_MESSAGE)
                return
            except (ExecutionFailure, RetryableExecutionError, ValueError) as exc:
                result = PageResult(method="vision", error=_plain(exc))
            await self._commit_page(org, job_id, token, index, result)
        await self._finish(org, job_id, token)

    # -- phases --

    async def _claim(self, org: str, job_id: str, token: str) -> ImportJob | None:
        async def body(tx: BankTx) -> ImportJob | None:
            job = await tx.imports.get(org, job_id)
            now = self._clock.now()
            if job is None or job.kind is not ImportKind.FILES:
                return None
            running = job.status is ImportStatus.RUNNING
            if job.status not in (ImportStatus.QUEUED, ImportStatus.RUNNING) or (
                running and job.lease is not None and job.lease.expires_at > now
            ):
                return None
            claimed = replace(
                job,
                status=ImportStatus.RUNNING,
                updated_at=now,
                lease=ImportLease(
                    worker_id=self._worker, token=token, expires_at=now + self._lease
                ),
            )
            tx.imports.save(claimed)
            return claimed

        return await self._uow.transaction(body)

    async def _read_page(self, org: str, source_id: str, number: int) -> SourcePage | None:
        async def body(tx: BankTx) -> SourcePage | None:
            return await tx.sources.get_page(org, source_id, number)

        return await self._uow.transaction(body)

    async def _extract(self, org: str, job: ImportJob, page: SourcePage | None) -> PageResult:
        if page is None:
            return PageResult(method="text-layer", error="The page is missing.")
        text = page.text or ""
        if text.strip():
            parsed = parse_text(text)
            usable = [q for q in parsed.questions if q.choices or q.answer]
            if parsed.questions and len(usable) * 2 >= len(parsed.questions):
                return PageResult(
                    method="text-layer",
                    questions=parsed.questions,
                    passages=parsed.passages,
                    answer_key=parsed.answer_key,
                )
            if not parsed.questions and parsed.answer_key:
                return PageResult(method="text-layer", answer_key=parsed.answer_key)
        if self._gateway is None:
            return PageResult(
                method="text-layer",
                error="No questions could be read from the text, and model extraction is not "
                "available in this environment.",
            )
        out = await question_extraction.extract_page(
            self._gateway, page, org_id=org, job_id=job.job_id, title=job.source_title
        )
        return PageResult(
            method="vision",
            questions=out.questions,
            flags=out.flags,
            passages=out.passages,
            answer_key=out.answer_key,
            tokens=out.usage_tokens,
            error=None if (out.questions or out.answer_key) else "No questions found on this page.",
        )

    async def _commit_page(
        self, org: str, job_id: str, token: str, index: int, r: PageResult
    ) -> None:
        async def body(tx: BankTx) -> None:
            job = await self._held(tx, org, job_id, token)
            task = job.pages[index]
            now = self._clock.now()
            stem = job_id.removeprefix("imp_")
            passage_ids: dict[str, str] = {}
            for p in r.passages:
                if not any(q.passage_ref == p.ref for q in r.questions):
                    continue
                pid = f"bkp_{stem}_{index:03d}_{p.ref}"[:64]
                passage_ids[p.ref] = pid
                if await tx.passages.get(org, pid) is None:
                    tx.passages.save(
                        BankPassage(
                            passage_id=pid,
                            org_id=org,
                            title=p.title or "Passage",
                            text=p.text[:MAX_PASSAGE_CHARS],
                            provenance=Provenance(
                                kind=ProvenanceKind.IMPORTED,
                                source_id=task.source_id,
                                page=task.page,
                                import_job_id=job_id,
                                reference=job.source_title,
                            ),
                            created_by=job.created_by,
                            created_at=now,
                            flags=(f"import:{job_id}",),
                        )
                    )
            item_ids: list[str] = []
            for q in r.questions:
                iid = f"bki_{stem}_{index:03d}_{q.number:03d}"[:64]
                item_ids.append(iid)
                if await tx.items.get(org, iid) is not None:
                    continue  # retried page: already written
                self._save_item(tx, org, job, task, iid, q, passage_ids, r, now)
            pages = list(job.pages)
            pages[index] = replace(
                task,
                status=PageStatus.FAILED if r.error and not item_ids else PageStatus.DONE,
                item_ids=tuple(item_ids),
                method=r.method,
                error=r.error,
            )
            tx.imports.save(
                replace(
                    job,
                    pages=tuple(pages),
                    item_ids=tuple(dict.fromkeys((*job.item_ids, *item_ids))),
                    passage_ids=tuple(dict.fromkeys((*job.passage_ids, *passage_ids.values()))),
                    item_count=len(set(job.item_ids) | set(item_ids)),
                    answer_key={**job.answer_key, **r.answer_key},
                    tokens_used=job.tokens_used + r.tokens,
                    errors=(*job.errors, f"page {task.page}: {r.error}") if r.error else job.errors,
                    updated_at=now,
                    lease=replace(job.lease, expires_at=now + self._lease) if job.lease else None,
                )
            )

        await self._uow.transaction(body)

    def _save_item(
        self,
        tx: BankTx,
        org: str,
        job: ImportJob,
        task: ImportPage,
        iid: str,
        q: ProposedQuestion,
        passage_ids: Mapping[str, str],
        r: PageResult,
        now: datetime,
    ) -> None:
        flags = [f"import:{job.job_id}", r.method, *r.flags.get(q.number, ())]
        for problem in q.problems:
            if problem.startswith("choices A–D incomplete"):
                flags.append("choices-incomplete")
            elif "numbers skipped" in problem:
                flags.append("number-uncertain")
        answer = q.answer
        if answer is None:
            flags.append("key-missing")
        content = ItemContent(
            stem=q.stem,
            item_type=ItemType.SPR if q.item_type == "spr" else ItemType.MC,
            choices=dict(q.choices) if q.choices else None,
            answer=answer,
            answer_source=(job.key_origin or AnswerSource.SOURCE_KEY) if answer else None,
            passage_id=passage_ids.get(q.passage_ref) if q.passage_ref else None,
            figure=FigureMode.DESCRIBED if "figure-described" in flags else FigureMode.NONE,
            flags=tuple(dict.fromkeys(flags)),
        )
        tx.items.save_version(
            org,
            BankItemVersion(
                item_id=iid,
                number=1,
                state=BankItemState.EXTRACTED,
                content=content,
                provenance=Provenance(
                    kind=ProvenanceKind.IMPORTED,
                    source_id=task.source_id,
                    page=task.page,
                    region=f"question {q.number}",
                    import_job_id=job.job_id,
                    reference=job.source_title,
                ),
                created_by=job.created_by,
                created_at=now,
                updated_at=now,
            ),
        )
        tx.items.save(
            BankItem(
                item_id=iid,
                org_id=org,
                course_id=job.course_hint,
                state=BankItemState.EXTRACTED,
                current_version=1,
                approved_version=None,
                revision=1,
                tags=(),
                flags=content.flags,
                content_hash=content_hash(content.stem, content.choices),
                created_by=job.created_by,
                created_at=now,
                updated_at=now,
                history=(
                    ItemChange(
                        action="import",
                        version=1,
                        actor_id=job.created_by,
                        at=now,
                        to_state=BankItemState.EXTRACTED,
                        notes=f"{job.job_id} page {task.page} ({r.method})",
                    ),
                ),
            )
        )

    async def _finish(self, org: str, job_id: str, token: str) -> None:
        """Apply answer-key pages to unkeyed questions (by number; ambiguous numbers are
        flagged, never guessed), then close the job. Chunked to stay inside transaction limits."""
        job = await self._snapshot(org, job_id, token)
        if job.answer_key:
            ids = list(job.item_ids)
            for start in range(0, len(ids), 150):
                await self._apply_keys(org, job_id, token, ids, ids[start : start + 150])

        async def close(tx: BankTx) -> None:
            job = await self._held(tx, org, job_id, token)
            failed = all(p.status is PageStatus.FAILED for p in job.pages)
            tx.imports.save(
                replace(
                    job,
                    status=ImportStatus.FAILED if failed else ImportStatus.SUCCEEDED,
                    lease=None,
                    updated_at=self._clock.now(),
                )
            )

        await self._uow.transaction(close)

    async def _apply_keys(
        self, org: str, job_id: str, token: str, all_ids: Sequence[str], chunk: Sequence[str]
    ) -> None:
        async def body(tx: BankTx) -> None:
            job = await self._held(tx, org, job_id, token)
            now = self._clock.now()
            counts: dict[int, int] = {}
            for iid in all_ids:  # item ids encode the question number as their last part
                n = int(iid.rsplit("_", 1)[-1]) if iid.rsplit("_", 1)[-1].isdigit() else -1
                counts[n] = counts.get(n, 0) + 1
            for iid in chunk:
                item = await tx.items.get(org, iid)
                if item is None or item.state is not BankItemState.EXTRACTED:
                    continue
                version = await tx.items.get_version(org, iid, item.current_version)
                if version is None or version.content.answer is not None:
                    continue
                number = _number(version.provenance.region)
                key = job.answer_key.get(number) if number is not None else None
                if number is None or key is None:
                    continue
                c = version.content
                if counts.get(number, 0) > 1:
                    flags = (*c.flags, "key-ambiguous")
                    content = replace(c, flags=tuple(dict.fromkeys(flags)))
                    action = "flag"
                elif c.item_type is ItemType.MC and key.upper() not in "ABCD":
                    continue
                else:
                    flags = tuple(f for f in c.flags if f != "key-missing")
                    content = replace(
                        c,
                        answer=key.upper() if c.item_type is ItemType.MC else key,
                        answer_source=job.key_origin or AnswerSource.SOURCE_KEY,
                        flags=tuple(dict.fromkeys((*flags, "key-from-answer-page"))),
                    )
                    action = "import-key"
                tx.items.save_version(org, replace(version, content=content, updated_at=now))
                tx.items.save(
                    replace(
                        item,
                        flags=content.flags,
                        revision=item.revision + 1,
                        updated_at=now,
                        history=(
                            *item.history,
                            ItemChange(
                                action=action,
                                version=item.current_version,
                                actor_id=job.created_by,
                                at=now,
                                from_state=item.state,
                                to_state=item.state,
                                notes=f"answer-key page of {job_id}",
                            ),
                        ),
                    )
                )

        await self._uow.transaction(body)

    async def _fail(self, org: str, job_id: str, token: str, message: str) -> None:
        async def body(tx: BankTx) -> None:
            job = await self._held(tx, org, job_id, token)
            tx.imports.save(
                replace(
                    job,
                    status=ImportStatus.FAILED,
                    errors=(*job.errors, message),
                    lease=None,
                    updated_at=self._clock.now(),
                )
            )

        await self._uow.transaction(body)

    async def _snapshot(self, org: str, job_id: str, token: str) -> ImportJob:
        async def body(tx: BankTx) -> ImportJob:
            return await self._held(tx, org, job_id, token)

        return await self._uow.transaction(body)

    @staticmethod
    async def _held(tx: BankTx, org: str, job_id: str, token: str) -> ImportJob:
        job = await tx.imports.get(org, job_id)
        if job is None or job.lease is None or job.lease.token != token:
            raise StaleLease(job_id)
        return job


def _plain(exc: Exception) -> str:
    code = getattr(exc, "code", None)
    if code == "MODEL_OUTPUT_INVALID":
        return "The model's reading of this page could not be used; try the page again."
    if code in ("MODEL_UNAVAILABLE", "MODEL_REFUSED") or isinstance(exc, RetryableExecutionError):
        return "The model could not read this page right now; try again later."
    return str(exc) or "This page could not be read."
