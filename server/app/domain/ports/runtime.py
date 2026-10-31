from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware UTC."""
        ...


class IdFactory(Protocol):
    def new(self, prefix: str) -> str:
        """An opaque, unguessable id such as `sess_3f9a...`."""
        ...
