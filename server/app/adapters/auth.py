"""Firebase ID token verification (Step 8).

`firebase_admin.auth.verify_id_token` checks signature, issuer (`securetoken.google.com/
<project>`), audience (`<project>`) and subject. Two gaps are closed here explicitly:

- In emulator mode the SDK skips signature verification *and* lifetime checks, so expiry
  and issued-at are re-checked against our own clock in every mode.
- Deployed environments cannot reach this code with emulator hosts set (`app.config`
  refuses to start), so unsigned emulator tokens are rejected there by the SDK.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from firebase_admin import auth as firebase_auth

from app.adapters.firebase import init_firebase_app
from app.config import Settings
from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.identity import VerifiedIdentity
from app.domain.ports.runtime import Clock

logger = logging.getLogger(__name__)

CLOCK_SKEW_SECONDS = 30
MAX_TOKEN_CHARS = 8192


def _unauthenticated(reason: str) -> DomainError:
    return DomainError(ErrorCode.UNAUTHENTICATED, reason)


def check_claims(claims: Mapping[str, Any], *, project_id: str, now: datetime) -> str:
    """Lifetime/audience/issuer checks that must hold regardless of SDK mode."""
    ts = int(now.timestamp())
    exp, iat = claims.get("exp"), claims.get("iat")
    if not isinstance(exp, int) or exp + CLOCK_SKEW_SECONDS <= ts:
        raise _unauthenticated("Token expired.")
    if not isinstance(iat, int) or iat - CLOCK_SKEW_SECONDS > ts:
        raise _unauthenticated("Token issued in the future.")
    if claims.get("aud") != project_id:
        raise _unauthenticated("Token audience mismatch.")
    if claims.get("iss") != f"https://securetoken.google.com/{project_id}":
        raise _unauthenticated("Token issuer mismatch.")
    uid = claims.get("sub")
    if not isinstance(uid, str) or not uid or len(uid) > 128:
        raise _unauthenticated("Token subject missing.")
    return uid


class FirebaseTokenVerifier:
    def __init__(self, settings: Settings, clock: Clock) -> None:
        self._settings = settings
        self._clock = clock
        self._app: Any = None

    def _firebase_app(self) -> Any:
        if self._app is None:
            self._app = init_firebase_app(self._settings)
        return self._app

    async def verify(self, token: str) -> VerifiedIdentity:
        if not token or len(token) > MAX_TOKEN_CHARS:
            raise _unauthenticated("Malformed token.")
        app = self._firebase_app()
        try:
            # May fetch Google's public certs (cached), so keep it off the event loop.
            claims: dict[str, Any] = await asyncio.to_thread(
                firebase_auth.verify_id_token, token, app=app
            )
        except firebase_auth.CertificateFetchError as exc:
            raise DomainError(
                ErrorCode.SERVICE_UNAVAILABLE, "Cannot verify sign-in right now.", retryable=True
            ) from exc
        except (firebase_auth.InvalidIdTokenError, ValueError) as exc:
            # Expired, revoked, wrong audience/issuer, bad signature, or malformed.
            logger.info("token_rejected", extra={"error": type(exc).__name__})
            raise _unauthenticated("Invalid or expired token.") from exc
        uid = check_claims(
            claims,
            project_id=self._settings.gcp_project_id,
            now=self._clock.now().astimezone(UTC),
        )
        exp = claims.get("exp")
        expires_at = datetime.fromtimestamp(exp, UTC) if isinstance(exp, int) else None
        return VerifiedIdentity(uid=uid, expires_at=expires_at)
