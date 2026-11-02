"""Operational metrics (Step 31.2). Names and labels are code constants, never content."""

from __future__ import annotations

from typing import Protocol


class Metrics(Protocol):
    def count(self, name: str, value: int = 1, **labels: str) -> None: ...

    def observe(self, name: str, value: float, **labels: str) -> None:
        """A measurement (latency in ms, tokens, backlog size)."""
        ...


class NullMetrics:
    def count(self, name: str, value: int = 1, **labels: str) -> None:
        return None

    def observe(self, name: str, value: float, **labels: str) -> None:
        return None
