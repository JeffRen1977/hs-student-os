from __future__ import annotations

from app.adapters.firestore import paths
from app.adapters.firestore.documents import DocTxn
from app.domain.types.actor import ActorContext
from app.domain.types.tool import ToolResult
from app.domain.types.usage import BudgetScope, Reservation, UsageCounter


class FirestoreUsageStore:
    """`students/{id}/usage/{key}`: one counter per run, session and UTC day."""

    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext, key: str) -> UsageCounter | None:
        d = await self._txn.get(paths.sub(actor, "usage", key))
        if d is None:
            return None
        return UsageCounter(
            key=d["key"],
            scope=BudgetScope(d["scope"]),
            used_tokens=int(d.get("usedTokens", 0)),
            reservations={
                k: Reservation(tokens=int(v["tokens"]), reserved_at=v["reservedAt"])
                for k, v in d.get("reservations", {}).items()
            },
            updated_at=d.get("updatedAt"),
        )

    def save(self, actor: ActorContext, c: UsageCounter) -> None:
        self._txn.set(
            paths.sub(actor, "usage", c.key),
            {
                "key": c.key,
                "scope": c.scope.value,
                "usedTokens": c.used_tokens,
                "reservations": {
                    k: {"tokens": r.tokens, "reservedAt": r.reserved_at}
                    for k, r in c.reservations.items()
                },
                "updatedAt": c.updated_at,
            },
        )


class FirestoreToolResultStore:
    """`students/{id}/toolResults/{id}`: the run's tool ledger (status + output only)."""

    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    def create(self, actor: ActorContext, r: ToolResult) -> None:
        if r.student_id != actor.student_id:
            raise ValueError("tool result does not belong to actor")
        self._txn.set(
            paths.sub(actor, "toolResults", r.tool_result_id),
            {
                "toolResultId": r.tool_result_id,
                "studentId": r.student_id,
                "runId": r.run_id,
                "tool": r.tool,
                "status": r.status.value,
                "output": dict(r.output),
                "createdAt": r.created_at,
            },
        )
