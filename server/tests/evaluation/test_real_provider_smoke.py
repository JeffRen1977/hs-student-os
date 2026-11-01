"""REAL-PROVIDER SMOKE TEST (Step 16.5). Calls the configured model API and costs money.

Skipped unless explicitly enabled. Provider and key come from the environment or `.env`:
    HSOS_RUN_REAL_LLM_SMOKE=1 HSOS_LLM_PROVIDER=anthropic|openai \
    uv run pytest tests/evaluation/test_real_provider_smoke.py
It checks plumbing only (structured output, usage, model version). It is not a quality
evaluation; that is `scripts/run_calc_evaluation.py` (Step 21).
"""

from __future__ import annotations

import os

import pytest

from app.adapters.firestore.memory_store import MemoryDocumentStore
from app.adapters.firestore.unit_of_work import DocumentUnitOfWork
from app.adapters.llm.gateway import Gateway
from app.bootstrap import model_router, real_llm_provider
from app.config import LlmProvider, Settings
from app.domain.budget import BudgetLedger, BudgetLimits
from app.domain.ports.content import ModelTier
from app.domain.ports.llm import BudgetContext, Effort, LlmMessage, LlmRequest, LlmRole
from app.domain.skills.socratic_guidance import OUTPUT_SCHEMA, parse_reply
from app.domain.types.usage import BudgetScope
from tests.support import FakeClock, SequentialIds

pytestmark = [
    pytest.mark.real_provider,
    pytest.mark.skipif(
        os.environ.get("HSOS_RUN_REAL_LLM_SMOKE") != "1",
        reason="real-provider smoke test disabled (set HSOS_RUN_REAL_LLM_SMOKE=1)",
    ),
]


async def test_structured_hint_round_trip() -> None:
    settings = Settings()
    if settings.llm_provider is LlmProvider.MOCK:
        pytest.skip("set HSOS_LLM_PROVIDER=anthropic|openai")
    store = MemoryDocumentStore()
    ledger = BudgetLedger(
        DocumentUnitOfWork(store), FakeClock(), SequentialIds(),
        BudgetLimits(run_tokens=20_000, session_tokens=20_000, daily_tokens=20_000),
    )  # fmt: skip
    gateway = Gateway(real_llm_provider(settings), model_router(settings), ledger, max_attempts=2)
    result = await gateway.generate(
        LlmRequest(
            purpose="socratic-guidance",
            pack_tier=ModelTier.FAST,
            workflow_version="smoke",
            system="You are a calculus tutor. Reply with one guiding question as JSON.",
            messages=[LlmMessage(role=LlmRole.USER, text="How do I differentiate sin(x^2)?")],
            output_schema=OUTPUT_SCHEMA,
            max_output_tokens=800,
            effort=Effort.LOW,
            budget=BudgetContext(student_id="stu_smoke", session_id="sess_smoke", run_id="run"),
        ),
        parse_reply,
    )
    assert result.value.strip()
    assert result.model_version  # the provider's exact model version, recorded per run
    assert result.usage.input_tokens > 0 and result.usage.output_tokens > 0
    used = store.raw(f"students/stu_smoke/usage/{BudgetScope.RUN.value}-run")
    assert used["usedTokens"] == result.usage.total
