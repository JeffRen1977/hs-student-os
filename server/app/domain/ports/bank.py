"""Ports for the organization question bank (Step 45, doc/QUESTION_BANK.md).

Bank records live under `orgs/{orgId}/…`, outside every student's subtree. Every store
method takes the organization id explicitly; services pass the caller's own organization,
so another organization's items are simply not found.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from app.domain.ports.packages import PlatformIdempotencyStore
from app.domain.types.bank import (
    BankItem,
    BankItemState,
    BankItemVersion,
    BankPassage,
    Selection,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class ItemQuery:
    state: BankItemState | None = None
    course_id: str | None = None
    flag: str | None = None
    approved_only: bool = False
    after_item_id: str | None = None  # keyset cursor (items are listed by itemId)
    limit: int = 50


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


class BankTx(Protocol):
    @property
    def items(self) -> BankItemStore: ...

    @property
    def passages(self) -> BankPassageStore: ...

    @property
    def selections(self) -> SelectionStore: ...

    @property
    def idempotency(self) -> PlatformIdempotencyStore: ...


class BankUnitOfWork(Protocol):
    async def transaction[T](self, fn: Callable[[BankTx], Awaitable[T]]) -> T: ...
