"""Step 16: LLMGateway routing, budgets, retries, output validation and usage logging."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from app.adapters.firestore.memory_store import MemoryDocumentStore
from app.adapters.firestore.unit_of_work import DocumentUnitOfWork
from app.adapters.llm.gateway import Gateway
from app.adapters.llm.provider import (
    ProviderPermanentError,
    ProviderRefusalError,
    ProviderTransientError,
)
from app.adapters.llm.router import ModelRouter
from app.domain.budget import BudgetLedger, BudgetLimits, day_key
from app.domain.ports.content import ModelTier
from app.domain.ports.llm import (
    BudgetContext,
    BudgetExceededError,
    Effort,
    LlmConfigurationError,
    LlmMessage,
    LlmOutputInvalidError,
    LlmRefusedError,
    LlmRequest,
    LlmRole,
    LlmUnavailableError,
)
from app.domain.types.usage import BudgetScope
from tests.support import FakeClock, ScriptedProvider, SequentialIds

MODELS = {
    ModelTier.FAST: "model-fast",
    ModelTier.BALANCED: "model-balanced",
    ModelTier.STRONG: "model-strong",
}
SECRET_ANSWER = "my private derivation 3x^2cos(x^3+1)"


def parse_reply(data: Any) -> str:
    if not isinstance(data, dict) or not isinstance(data.get("reply"), str):
        raise ValueError("bad shape")
    return str(data["reply"])


def request(
    *, purpose: str = "socratic-guidance", run_id: str = "run_1", session_id: str = "sess_1"
) -> LlmRequest:
    return LlmRequest(
        purpose=purpose,
        pack_tier=ModelTier.BALANCED,
        workflow_version="calc-practice-v1",
        system="system prompt",
        messages=[LlmMessage(role=LlmRole.USER, text=SECRET_ANSWER)],
        output_schema={"type": "object"},
        max_output_tokens=500,
        effort=Effort.LOW,
        budget=BudgetContext(student_id="stu_alex", session_id=session_id, run_id=run_id),
    )


class Rig:
    def __init__(self, provider: ScriptedProvider, **limits: int) -> None:
        self.store = MemoryDocumentStore()
        self.clock = FakeClock()
        self.sleeps: list[float] = []
        self.ledger = BudgetLedger(
            DocumentUnitOfWork(self.store),
            self.clock,
            SequentialIds(),
            BudgetLimits(
                run_tokens=limits.get("run", 50_000),
                session_tokens=limits.get("session", 100_000),
                daily_tokens=limits.get("day", 200_000),
            ),
        )

        async def sleep(seconds: float) -> None:
            self.sleeps.append(seconds)

        self.gateway = Gateway(
            provider, ModelRouter(MODELS), self.ledger, max_attempts=3, sleep=sleep
        )

    def used(self, key: str) -> int:
        doc = self.store.raw(f"students/stu_alex/usage/{key}")
        return int(doc["usedTokens"]) if doc else 0


def test_router_uses_pack_tier_but_never_below_the_skill_floor() -> None:
    router = ModelRouter(MODELS)
    assert router.route("socratic-guidance", ModelTier.BALANCED) == (
        ModelTier.BALANCED,
        "model-balanced",
    )
    assert router.route("socratic-guidance", ModelTier.FAST)[0] is ModelTier.FAST
    # Grading is pinned to the strong tier even when the pack asks for less.
    assert router.route("rubric-assessment", ModelTier.FAST) == (ModelTier.STRONG, "model-strong")
    with pytest.raises(ValueError):
        router.route("unknown-skill", ModelTier.FAST)
    with pytest.raises(ValueError):
        ModelRouter({ModelTier.FAST: "x"})


async def test_success_reports_model_workflow_tier_and_usage() -> None:
    provider = ScriptedProvider({"reply": "What is the inner function?"})
    rig = Rig(provider)
    result = await rig.gateway.generate(request(), parse_reply)
    assert result.value == "What is the inner function?"
    assert result.model_version == ScriptedProvider.MODEL_VERSION
    assert result.workflow_version == "calc-practice-v1"
    assert (result.tier, result.attempts, result.usage.total) == (ModelTier.BALANCED, 1, 150)
    assert provider.calls[0]["model"] == "model-balanced"
    for key in ("run-run_1", "session-sess_1", day_key(rig.clock.now())):
        assert rig.used(key) == 150
    doc = rig.store.raw("students/stu_alex/usage/run-run_1")
    assert doc["reservations"] == {}  # reservation settled


async def test_timeout_retries_with_backoff_then_fails_gracefully() -> None:
    provider = ScriptedProvider(*(ProviderTransientError("APITimeoutError") for _ in range(3)))
    rig = Rig(provider)
    with pytest.raises(LlmUnavailableError):
        await rig.gateway.generate(request(), parse_reply)
    assert len(provider.calls) == 3
    assert rig.sleeps == [0.5, 1.0]  # exponential backoff between attempts
    assert rig.used("run-run_1") > 0  # failed attempts are still charged


async def test_transient_error_then_success() -> None:
    provider = ScriptedProvider(ProviderTransientError("overloaded"), {"reply": "ok"})
    result = await Rig(provider).gateway.generate(request(), parse_reply)
    assert (result.value, result.attempts) == ("ok", 2)


async def test_schema_validation_failure_retries_then_fails() -> None:
    provider = ScriptedProvider("not json", {"wrong": 1}, {"reply": "finally"})
    result = await Rig(provider).gateway.generate(request(), parse_reply)
    assert (result.value, result.attempts) == ("finally", 3)
    assert result.usage.total == 450  # every attempt is counted

    provider = ScriptedProvider("{", {"wrong": 1}, {"wrong": 2})
    with pytest.raises(LlmOutputInvalidError) as err:
        await Rig(provider).gateway.generate(request(), parse_reply)
    assert err.value.code == "MODEL_OUTPUT_INVALID"


async def test_refusal_and_permanent_errors_are_not_retried() -> None:
    provider = ScriptedProvider(ProviderRefusalError("refusal", input_tokens=10))
    with pytest.raises(LlmRefusedError):
        await Rig(provider).gateway.generate(request(), parse_reply)
    assert len(provider.calls) == 1
    provider = ScriptedProvider(ProviderPermanentError("BadRequestError:400"))
    with pytest.raises(LlmConfigurationError):
        await Rig(provider).gateway.generate(request(), parse_reply)
    assert len(provider.calls) == 1


async def test_budget_exhaustion_is_rejected_before_the_provider_is_called() -> None:
    provider = ScriptedProvider({"reply": "never"})
    rig = Rig(provider, run=200)  # smaller than one call's worst-case reservation
    with pytest.raises(BudgetExceededError) as err:
        await rig.gateway.generate(request(), parse_reply)
    assert err.value.scope is BudgetScope.RUN and err.value.code == "BUDGET_EXCEEDED"
    assert provider.calls == []


async def test_session_and_daily_budgets_span_runs() -> None:
    replies = [{"reply": str(i)} for i in range(5)]
    # 500 tokens per call; each call first reserves ~585 (input estimate + max output).
    rig = Rig(ScriptedProvider(*replies, input_tokens=400, output_tokens=100), session=1_200)
    await rig.gateway.generate(request(run_id="run_a"), parse_reply)
    await rig.gateway.generate(request(run_id="run_b"), parse_reply)
    with pytest.raises(BudgetExceededError) as err:  # the session's remaining budget is spent
        await rig.gateway.generate(request(run_id="run_c"), parse_reply)
    assert err.value.scope is BudgetScope.SESSION

    rig = Rig(ScriptedProvider(*replies, input_tokens=400, output_tokens=100), day=1_200)
    await rig.gateway.generate(request(run_id="r1", session_id="s1"), parse_reply)
    await rig.gateway.generate(request(run_id="r2", session_id="s2"), parse_reply)
    with pytest.raises(BudgetExceededError) as err:
        await rig.gateway.generate(request(run_id="r3", session_id="s3"), parse_reply)
    assert err.value.scope is BudgetScope.DAY


async def test_reservations_from_a_crashed_worker_expire() -> None:
    rig = Rig(ScriptedProvider({"reply": "ok"}), run=1_200)
    ctx = request().budget
    await rig.ledger.reserve(ctx, 1_000)  # never settled: the worker "crashed"
    with pytest.raises(BudgetExceededError):
        await rig.ledger.reserve(ctx, 1_000)
    rig.clock.advance(seconds=rig.ledger.limits.reservation_ttl_seconds + 1)
    await rig.ledger.reserve(ctx, 1_000)  # the stale reservation no longer counts


async def test_logs_capture_model_and_tokens_but_no_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = ScriptedProvider("garbage", {"reply": "Think about the inner function."})
    with caplog.at_level(logging.INFO, logger="app.llm"):
        await Rig(provider).gateway.generate(request(), parse_reply)
    records = [r for r in caplog.records if r.name == "app.llm"]
    assert [r.getMessage() for r in records] == ["llm_output_invalid", "llm_call_succeeded"]
    final = records[-1].__dict__
    assert final["model"] == "model-balanced" and final["tier"] == "balanced"
    assert final["tokens"] == 150 and final["runId"] == "run_1" and "latencyMs" in final
    dumped = " ".join(str(r.__dict__) for r in records)
    assert SECRET_ANSWER not in dumped and "inner function" not in dumped
