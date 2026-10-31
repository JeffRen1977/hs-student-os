from __future__ import annotations

import secrets
from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class RandomIdFactory:
    def new(self, prefix: str) -> str:
        return f"{prefix}_{secrets.token_hex(10)}"
