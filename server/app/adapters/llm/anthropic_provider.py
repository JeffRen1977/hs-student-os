"""Anthropic Claude provider (Step 16.1). The SDK's own retries are disabled so that the
gateway owns retry policy and every attempt is budgeted.

Server-side refusal fallbacks are intentionally *not* enabled: a fallback would silently
answer (or grade) with a different, unevaluated model, which BACKEND.md §7 forbids. A
refusal fails the run with MODEL_REFUSED instead.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import anthropic
from anthropic.types import MessageParam

from app.adapters.llm.provider import (
    ProviderPermanentError,
    ProviderRefusalError,
    ProviderResponse,
    ProviderTransientError,
    ProviderTruncatedError,
)
from app.domain.ports.llm import Effort, LlmMessage, LlmRole

TRANSIENT_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504, 529})


class AnthropicProvider:
    def __init__(self, client: anthropic.AsyncAnthropic) -> None:
        self._client = client

    @classmethod
    def from_api_key(cls, api_key: str | None) -> AnthropicProvider:
        # None → the SDK reads ANTHROPIC_API_KEY from the process environment. Never logged.
        return cls(anthropic.AsyncAnthropic(api_key=api_key, max_retries=0))

    @classmethod
    def from_environment(cls) -> AnthropicProvider:
        # Credentials resolve from the environment (ANTHROPIC_API_KEY, mounted from Secret
        # Manager when deployed). Never logged, never stored in settings.
        return cls(anthropic.AsyncAnthropic(max_retries=0))

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
    ) -> ProviderResponse:
        params: list[MessageParam] = []
        for m in messages:
            if m.role is LlmRole.USER:
                params.append({"role": "user", "content": m.text})
            else:
                params.append({"role": "assistant", "content": m.text})
        try:
            response = await self._client.messages.create(
                model=model,
                max_tokens=max_output_tokens,
                system=system,
                messages=params,
                output_config={
                    "effort": effort.value,
                    "format": {"type": "json_schema", "schema": dict(output_schema)},
                },
                timeout=timeout_seconds,
            )
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
            raise ProviderTransientError(type(exc).__name__) from exc
        except anthropic.APIStatusError as exc:
            name = f"{type(exc).__name__}:{exc.status_code}"
            if exc.status_code in TRANSIENT_STATUS or exc.status_code >= 500:
                raise ProviderTransientError(name) from exc
            raise ProviderPermanentError(name) from exc

        usage = response.usage
        tokens = {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}
        if response.stop_reason == "refusal":
            raise ProviderRefusalError("refusal", **tokens)
        if response.stop_reason == "max_tokens":
            raise ProviderTruncatedError("max_tokens", **tokens)
        text = "".join(block.text for block in response.content if block.type == "text")
        return ProviderResponse(text=text, model_version=response.model, **tokens)
