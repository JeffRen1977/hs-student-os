from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifiedIdentity:
    uid: str
    expires_at: datetime | None = None  # token lifetime; long-lived streams end here


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> VerifiedIdentity:
        """Verify signature, issuer, audience and lifetime. Raise DomainError
        UNAUTHENTICATED on any failure."""
        ...
