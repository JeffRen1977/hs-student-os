"""OpenAI provider (Responses API) behind the same `LlmProvider` seam as Anthropic.

Same rules as the Anthropic adapter: the SDK's own retries are disabled so the gateway owns
retry policy and every attempt is budgeted; structured output is enforced with a strict JSON
schema; a refusal fails the run (MODEL_REFUSED) instead of falling back to another model;
responses are not stored on OpenAI's side (`store=False`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import openai
from openai.types.responses import ResponseInputParam
from openai.types.shared_params import Reasoning

from app.adapters.llm.provider import (
    ProviderPermanentError,
    ProviderRefusalError,
    ProviderResponse,
    ProviderTransientError,
    ProviderTruncatedError,
)
from app.domain.ports.llm import Effort, LlmMessage, LlmRole

REASONING: dict[Effort, Reasoning] = {
    Effort.LOW: {"effort": "low"},
    Effort.MEDIUM: {"effort": "medium"},
    Effort.HIGH: {"effort": "high"},
}

TRANSIENT_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})


class OpenAIProvider:
    def __init__(self, client: openai.AsyncOpenAI) -> None:
        self._client = client

    @classmethod
    def from_api_key(cls, api_key: str | None) -> OpenAIProvider:
        # None → the SDK reads OPENAI_API_KEY from the process environment. Never logged.
        return cls(openai.AsyncOpenAI(api_key=api_key, max_retries=0))

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
        params: ResponseInputParam = []
        for m in messages:
            if m.role is LlmRole.USER:
                params.append({"role": "user", "content": m.text})
            else:
                params.append({"role": "assistant", "content": m.text})
        try:
            response = await self._client.responses.create(
                model=model,
                instructions=system,
                input=params,
                max_output_tokens=max_output_tokens,
                reasoning=REASONING[effort],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "output",
                        "schema": dict(output_schema),
                        "strict": True,
                    }
                },
                store=False,
                timeout=timeout_seconds,
            )
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            raise ProviderTransientError(type(exc).__name__) from exc
        except openai.APIStatusError as exc:
            name = f"{type(exc).__name__}:{exc.status_code}"
            if exc.status_code in TRANSIENT_STATUS or exc.status_code >= 500:
                raise ProviderTransientError(name) from exc
            raise ProviderPermanentError(name) from exc

        usage = response.usage
        tokens = {
            "input_tokens": usage.input_tokens if usage else 0,
            "output_tokens": usage.output_tokens if usage else 0,
        }
        texts: list[str] = []
        for item in response.output:
            if item.type != "message":
                continue  # reasoning items carry no answer text
            for part in item.content:
                if part.type == "refusal":
                    raise ProviderRefusalError("refusal", **tokens)
                if part.type == "output_text":
                    texts.append(part.text)
        if response.status == "incomplete":
            reason = response.incomplete_details.reason if response.incomplete_details else None
            if reason == "content_filter":
                raise ProviderRefusalError("content_filter", **tokens)
            raise ProviderTruncatedError(reason or "incomplete", **tokens)
        if response.status == "failed":
            raise ProviderTransientError("response_failed", **tokens)
        return ProviderResponse(text="".join(texts), model_version=response.model, **tokens)
