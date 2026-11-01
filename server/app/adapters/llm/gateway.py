"""LLMGateway: the one path to a model (Step 16, BACKEND.md §7).

- routes by skill tier (static `ModelRouter`);
- reserves budget before every attempt and settles actual usage after it (retries are
  charged; a call that would exceed a budget is refused, never silently degraded);
- retries a finite number of times: transient provider errors with exponential backoff,
  and output that fails the caller's `parse` (schema or semantic validation);
- reports model version, workflow version, tier, attempts and summed usage;
- logs ids, tier, model, latency, token counts and outcomes. Never prompts, student work,
  model output, or credentials.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.adapters.llm.provider import (
    LlmProvider,
    ProviderPermanentError,
    ProviderRefusalError,
    ProviderTransientError,
    ProviderTruncatedError,
)
from app.adapters.llm.router import ModelRouter
from app.domain.budget import BudgetLedger
from app.domain.ports.llm import (
    LlmConfigurationError,
    LlmOutputInvalidError,
    LlmRefusedError,
    LlmRequest,
    LlmResult,
    LlmUnavailableError,
    LlmUsage,
)

logger = logging.getLogger("app.llm")

CHARS_PER_TOKEN = 3  # deliberately pessimistic estimate for reservations


def estimate_input_tokens(request: LlmRequest) -> int:
    chars = len(request.system) + sum(len(m.text) for m in request.messages)
    chars += len(json.dumps(request.output_schema))
    return chars // CHARS_PER_TOKEN + 64


class Gateway:
    def __init__(
        self,
        provider: LlmProvider,
        router: ModelRouter,
        ledger: BudgetLedger,
        *,
        max_attempts: int = 3,
        timeout_seconds: float = 60.0,
        backoff_seconds: float = 0.5,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._provider = provider
        self._router = router
        self._ledger = ledger
        self._max_attempts = max_attempts
        self._timeout = timeout_seconds
        self._backoff = backoff_seconds
        self._sleep = sleep

    async def generate[T](self, request: LlmRequest, parse: Callable[[Any], T]) -> LlmResult[T]:
        tier, model = self._router.route(request.purpose, request.pack_tier)
        input_estimate = estimate_input_tokens(request)
        reservation = input_estimate + request.max_output_tokens
        used_in, used_out = 0, 0
        last_transient = False
        log = {"runId": request.budget.run_id, "purpose": request.purpose, "tier": tier.value,
               "model": model}  # fmt: skip

        for attempt in range(1, self._max_attempts + 1):
            # Raises BudgetExceededError before contacting the provider.
            hold = await self._ledger.reserve(request.budget, reservation)
            started = time.monotonic()
            charged = 0
            try:
                response = await self._provider.complete(
                    model=model,
                    system=request.system,
                    messages=request.messages,
                    output_schema=request.output_schema,
                    max_output_tokens=request.max_output_tokens,
                    effort=request.effort,
                    timeout_seconds=self._timeout,
                )
            except ProviderTransientError as exc:
                # Usage is unknown after a timeout; charge the input estimate.
                charged = input_estimate
                used_in += input_estimate
                last_transient = True
                self._log("llm_attempt_failed", log, attempt, started, exc, charged)
                await self._ledger.settle(request.budget, hold, charged)
                if attempt < self._max_attempts:
                    await self._sleep(self._backoff * 2 ** (attempt - 1))
                continue
            except ProviderRefusalError as exc:
                await self._ledger.settle(
                    request.budget, hold, exc.input_tokens + exc.output_tokens
                )
                self._log("llm_refused", log, attempt, started, exc, exc.input_tokens)
                raise LlmRefusedError() from exc
            except ProviderPermanentError as exc:
                await self._ledger.settle(request.budget, hold, 0)
                self._log("llm_provider_error", log, attempt, started, exc, 0)
                raise LlmConfigurationError() from exc
            except ProviderTruncatedError as exc:
                charged = exc.input_tokens + exc.output_tokens
                used_in += exc.input_tokens
                used_out += exc.output_tokens
                last_transient = False
                await self._ledger.settle(request.budget, hold, charged)
                self._log("llm_output_truncated", log, attempt, started, exc, charged)
                continue

            charged = response.input_tokens + response.output_tokens
            used_in += response.input_tokens
            used_out += response.output_tokens
            await self._ledger.settle(request.budget, hold, charged)
            try:
                value = parse(json.loads(response.text))
            except (ValueError, TypeError, KeyError) as exc:  # JSONDecodeError is a ValueError
                last_transient = False
                self._log("llm_output_invalid", log, attempt, started, exc, charged)
                continue
            self._log("llm_call_succeeded", log, attempt, started, None, charged)
            return LlmResult(
                value=value,
                model_version=response.model_version,
                workflow_version=request.workflow_version,
                tier=tier,
                usage=LlmUsage(input_tokens=used_in, output_tokens=used_out),
                attempts=attempt,
            )

        if last_transient:
            raise LlmUnavailableError("model provider unavailable after retries")
        raise LlmOutputInvalidError()

    @staticmethod
    def _log(
        event: str,
        base: dict[str, str],
        attempt: int,
        started: float,
        exc: BaseException | None,
        tokens: int,
    ) -> None:
        extra: dict[str, object] = {
            **base,
            "attempt": attempt,
            "latencyMs": round((time.monotonic() - started) * 1000),
            "tokens": tokens,
        }
        if exc is not None:
            extra["error"] = type(exc).__name__  # class name only: messages may echo input
        logger.info(event, extra=extra)
