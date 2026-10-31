"""Authenticate calls into the worker service (Step 15.3).

Student Firebase tokens are never valid here. Locally a shared service token is used;
deployed environments verify the Google-signed OIDC token Cloud Tasks attaches.
"""

from __future__ import annotations

import asyncio
import hmac
from typing import Any, Protocol

from pydantic import SecretStr

from app.domain.errors import DomainError, ErrorCode


class ServiceAuthenticator(Protocol):
    async def authenticate(self, bearer_token: str) -> str:
        """Return the verified service identity or raise UNAUTHENTICATED."""
        ...


def _denied() -> DomainError:
    return DomainError(ErrorCode.UNAUTHENTICATED, "Service authentication required.")


class LocalServiceTokenAuthenticator:
    def __init__(self, token: SecretStr) -> None:
        if len(token.get_secret_value()) < 16:
            raise ValueError("worker service token must be at least 16 characters")
        self._token = token

    async def authenticate(self, bearer_token: str) -> str:
        if not hmac.compare_digest(bearer_token.encode(), self._token.get_secret_value().encode()):
            raise _denied()
        return "local-service"


class GoogleOidcAuthenticator:
    def __init__(self, *, audience: str, service_account: str) -> None:
        self._audience = audience
        self._service_account = service_account

    async def authenticate(self, bearer_token: str) -> str:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        try:
            claims: dict[str, Any] = await asyncio.to_thread(
                id_token.verify_oauth2_token,
                bearer_token,
                google_requests.Request(),
                self._audience,
            )
        except ValueError as exc:
            raise _denied() from exc
        if claims.get("email") != self._service_account or not claims.get("email_verified"):
            raise _denied()
        return str(claims["email"])


class DenyAllAuthenticator:
    """Used when no worker credential is configured: internal routes stay closed."""

    async def authenticate(self, bearer_token: str) -> str:
        raise _denied()
