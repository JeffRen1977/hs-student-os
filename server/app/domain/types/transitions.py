"""Strict state-machine checks shared by all services (CLAUDE.md §2.5)."""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.errors import DomainError, ErrorCode


def ensure_transition[S](
    transitions: Mapping[S, frozenset[S]], current: S, target: S, *, entity: str
) -> None:
    if target not in transitions[current]:
        raise DomainError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"{entity} cannot move from {current} to {target}",
        )
