"""Model usage budgets: per Run, per Session, per student per UTC day (Step 16.3).

Every model call (retries included) first *reserves* its worst-case token cost against all
three counters in one transaction, then *settles* the actual usage. A call that would push
any counter past its limit is refused before the provider is contacted, so a budget can be
exhausted but never silently exceeded. Reservations left behind by a crashed worker expire
after `reservation_ttl_seconds` instead of locking the budget forever.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime

from app.domain.ports.llm import BudgetContext, BudgetExceededError
from app.domain.ports.repositories import Tx, UnitOfWork
from app.domain.ports.runtime import Clock, IdFactory
from app.domain.types.actor import ActorContext
from app.domain.types.usage import BudgetScope, Reservation, UsageCounter

BUDGET_SERVICE = "llm-budget"


@dataclass(frozen=True, slots=True, kw_only=True)
class BudgetLimits:
    run_tokens: int
    session_tokens: int
    daily_tokens: int
    reservation_ttl_seconds: int = 600


@dataclass(frozen=True, slots=True, kw_only=True)
class BudgetHold:
    """A reservation and the exact counters it was taken on (settled on the same ones)."""

    reservation_id: str
    tokens: int
    counters: tuple[tuple[BudgetScope, str], ...]


def usage_key(scope: BudgetScope, value: str) -> str:
    return f"{scope.value}-{value}"


def day_key(now: datetime) -> str:
    return usage_key(BudgetScope.DAY, now.date().isoformat())


class BudgetLedger:
    def __init__(self, uow: UnitOfWork, clock: Clock, ids: IdFactory, limits: BudgetLimits) -> None:
        self._uow = uow
        self._clock = clock
        self._ids = ids
        self.limits = limits

    def _scopes(self, ctx: BudgetContext, now: datetime) -> list[tuple[BudgetScope, str, int]]:
        scopes = [(BudgetScope.RUN, usage_key(BudgetScope.RUN, ctx.run_id), self.limits.run_tokens)]
        if ctx.session_id is not None:
            scopes.append(
                (
                    BudgetScope.SESSION,
                    usage_key(BudgetScope.SESSION, ctx.session_id),
                    self.limits.session_tokens,
                )
            )
        scopes.append((BudgetScope.DAY, day_key(now), self.limits.daily_tokens))
        return scopes

    def _live(self, counter: UsageCounter, now: datetime) -> dict[str, Reservation]:
        ttl = self.limits.reservation_ttl_seconds
        return {
            k: r
            for k, r in counter.reservations.items()
            if (now - r.reserved_at).total_seconds() < ttl
        }

    async def reserve(self, ctx: BudgetContext, tokens: int) -> BudgetHold:
        actor = ActorContext.for_service(BUDGET_SERVICE, ctx.student_id)
        reservation_id = self._ids.new("rsv")

        async def body(tx: Tx) -> BudgetHold:
            now = self._clock.now()
            scopes = self._scopes(ctx, now)
            pending: list[UsageCounter] = []
            for scope, key, limit in scopes:
                counter = await tx.usage.get(actor, key) or UsageCounter(key=key, scope=scope)
                live = self._live(counter, now)
                committed = counter.used_tokens + sum(r.tokens for r in live.values())
                if committed + tokens > limit:
                    raise BudgetExceededError(scope)
                live[reservation_id] = Reservation(tokens=tokens, reserved_at=now)
                pending.append(dataclasses.replace(counter, reservations=live, updated_at=now))
            for counter in pending:
                tx.usage.save(actor, counter)
            return BudgetHold(
                reservation_id=reservation_id,
                tokens=tokens,
                counters=tuple((scope, key) for scope, key, _ in scopes),
            )

        return await self._uow.transaction(body)

    async def settle(self, ctx: BudgetContext, hold: BudgetHold, used_tokens: int) -> None:
        """Replace the reservation with the tokens actually used (charged even on failure)."""
        actor = ActorContext.for_service(BUDGET_SERVICE, ctx.student_id)

        async def body(tx: Tx) -> None:
            now = self._clock.now()
            for scope, key in hold.counters:
                counter = await tx.usage.get(actor, key) or UsageCounter(key=key, scope=scope)
                live = self._live(counter, now)
                live.pop(hold.reservation_id, None)
                tx.usage.save(
                    actor,
                    dataclasses.replace(
                        counter,
                        used_tokens=counter.used_tokens + used_tokens,
                        reservations=live,
                        updated_at=now,
                    ),
                )

        await self._uow.transaction(body)

    async def exhausted_scope(
        self, tx: Tx, actor: ActorContext, session_id: str | None, now: datetime
    ) -> BudgetScope | None:
        """Used by command acceptance: refuse new work once a session/day budget is spent."""
        checks: list[tuple[str, int, BudgetScope]] = [
            (day_key(now), self.limits.daily_tokens, BudgetScope.DAY)
        ]
        if session_id is not None:
            checks.append(
                (
                    usage_key(BudgetScope.SESSION, session_id),
                    self.limits.session_tokens,
                    BudgetScope.SESSION,
                )
            )
        for key, limit, scope in checks:
            counter = await tx.usage.get(actor, key)
            if counter is not None and counter.used_tokens >= limit:
                return scope
        return None
