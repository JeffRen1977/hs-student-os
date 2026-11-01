"""Provider-facing seam under the gateway. Real providers: Anthropic, OpenAI; tests use fakes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.domain.ports.llm import Effort, LlmMessage


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model_version: str


class ProviderError(Exception):
    def __init__(self, message: str = "", *, input_tokens: int = 0, output_tokens: int = 0):
        super().__init__(message)
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class ProviderTransientError(ProviderError):
    """Timeout, connection failure, rate limit, overload, 5xx: worth retrying."""


class ProviderPermanentError(ProviderError):
    """Bad request, auth, unknown model: retrying will not help."""


class ProviderRefusalError(ProviderError):
    """The model declined (stop_reason=refusal). Not retried on another model."""


class ProviderTruncatedError(ProviderError):
    """Output hit max_tokens; treated like invalid output."""


class LlmProvider(Protocol):
    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[LlmMessage],
        output_schema: Mapping[str, Any],
        max_output_tokens: int,
        effort: Effort,
        timeout_seconds: float,
    ) -> ProviderResponse: ...
