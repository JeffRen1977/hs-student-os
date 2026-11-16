"""Ports for the organization question bank (Step 45, doc/QUESTION_BANK.md).

Bank records live under `orgs/{orgId}/…`, outside every student's subtree. Every store
method takes the organization id explicitly; services pass the caller's own organization,
so another organization's items are simply not found.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.domain.ports.packages import PlatformIdempotencyStore
from app.domain.types.bank import (
    BankItem,
    BankItemState,
    BankItemVersion,
    BankPassage,
    BankSource,
    ImportJob,
    Selection,
    SourcePage,
)
from app.domain.types.usage import UsageCounter


@dataclass(frozen=True, slots=True, kw_only=True)
class ItemQuery:
    state: BankItemState | None = None
    course_id: str | None = None
    flag: str | None = None
    approved_only: bool = False
    after_item_id: str | None = None  # keyset cursor (items are listed by itemId)
    limit: int = 50
    content_hashes: Sequence[str] = ()  # duplicate lookup: items whose hash is one of these (≤30)


class BankItemStore(Protocol):
    async def get(self, org_id: str, item_id: str) -> BankItem | None: ...

    async def get_version(
        self, org_id: str, item_id: str, number: int
    ) -> BankItemVersion | None: ...

    async def list_versions(self, org_id: str, item_id: str) -> Sequence[BankItemVersion]: ...

    async def query(self, org_id: str, q: ItemQuery) -> Sequence[BankItem]: ...

    def save(self, item: BankItem) -> None: ...

    def save_version(self, org_id: str, version: BankItemVersion) -> None: ...


class BankPassageStore(Protocol):
    async def get(self, org_id: str, passage_id: str) -> BankPassage | None: ...

    def save(self, passage: BankPassage) -> None: ...


class SelectionStore(Protocol):
    async def get(self, org_id: str, selection_id: str) -> Selection | None: ...

    async def list_for_org(self, org_id: str) -> Sequence[Selection]: ...

    def save(self, selection: Selection) -> None: ...


class ImportJobStore(Protocol):
    async def get(self, org_id: str, job_id: str) -> ImportJob | None: ...

    async def list_for_org(self, org_id: str, limit: int) -> Sequence[ImportJob]: ...

    def save(self, job: ImportJob) -> None: ...


class SourceStore(Protocol):
    async def get(self, org_id: str, source_id: str) -> BankSource | None: ...

    def save(self, source: BankSource) -> None: ...

    async def get_page(self, org_id: str, source_id: str, number: int) -> SourcePage | None: ...

    async def page_numbers(self, org_id: str, source_id: str) -> Sequence[int]: ...

    def save_page(self, org_id: str, page: SourcePage) -> None: ...


class OrgUsageStore(Protocol):
    """`orgs/{orgId}/usage/{key}`: model-token counters per import job and per UTC day."""

    async def get(self, org_id: str, key: str) -> UsageCounter | None: ...

    def save(self, org_id: str, counter: UsageCounter) -> None: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class FetchedLink:
    url: str  # after redirects
    content_type: str
    text: str  # readable text (HTML reduced to text)


class LinkFetcher(Protocol):
    async def fetch(self, url: str) -> FetchedLink:
        """Fetch a public http(s) page under the link guard (QUESTION_BANK.md §7.2); raises
        DomainError(IMPORT_SOURCE_REJECTED) with a plain-language reason otherwise."""
        ...


class ImportQueueReader(Protocol):
    async def due_jobs(self, now: datetime, limit: int) -> Sequence[tuple[str, str]]:
        """(orgId, jobId) of file jobs that are queued, or running with an expired lease.
        Service-only, across organizations."""
        ...


class BankTx(Protocol):
    @property
    def items(self) -> BankItemStore: ...

    @property
    def passages(self) -> BankPassageStore: ...

    @property
    def selections(self) -> SelectionStore: ...

    @property
    def imports(self) -> ImportJobStore: ...

    @property
    def sources(self) -> SourceStore: ...

    @property
    def org_usage(self) -> OrgUsageStore: ...

    @property
    def idempotency(self) -> PlatformIdempotencyStore: ...


class BankUnitOfWork(Protocol):
    async def transaction[T](self, fn: Callable[[BankTx], Awaitable[T]]) -> T: ...
