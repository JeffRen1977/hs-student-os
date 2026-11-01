"""Real provider adapters (Anthropic, OpenAI) against a fake HTTP transport.

The real SDKs build and parse the requests; only the network is replaced. This proves the
wire mapping (structured-output schema, effort, no SDK retries, no server-side storage) and
the error mapping the gateway relies on. It does not prove model quality.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import openai
import pytest

from app.adapters.llm.anthropic_provider import AnthropicProvider
from app.adapters.llm.openai_provider import OpenAIProvider
from app.adapters.llm.provider import (
    LlmProvider,
    ProviderPermanentError,
    ProviderRefusalError,
    ProviderTransientError,
    ProviderTruncatedError,
)
from app.bootstrap import real_llm_provider
from app.config import ConfigError, Settings
from app.config import LlmProvider as ProviderName
from app.domain.ports.llm import Effort, LlmMessage, LlmRole

SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"}},
    "required": ["reply"],
    "additionalProperties": False,
}
MESSAGES = [
    LlmMessage(role=LlmRole.USER, text="How do I start?"),
    LlmMessage(role=LlmRole.ASSISTANT, text="What rule applies?"),
    LlmMessage(role=LlmRole.USER, text="The chain rule?"),
]

Handler = Callable[[httpx2.Request], httpx2.Response]


class Recorder:
    def __init__(self, respond: Handler) -> None:
        self.requests: list[httpx2.Request] = []
        self._respond = respond

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self._respond(request)

    @property
    def body(self) -> dict[str, Any]:
        result: dict[str, Any] = json.loads(self.requests[-1].content)
        return result


def openai_provider(rec: Recorder) -> OpenAIProvider:
    client = openai.AsyncOpenAI(
        api_key="sk-test-not-real",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(rec)),
    )
    return OpenAIProvider(client)


def anthropic_provider(rec: Recorder) -> AnthropicProvider:
    client = anthropic.AsyncAnthropic(
        api_key="sk-ant-test-not-real",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(rec)),
    )
    return AnthropicProvider(client)


async def call(provider: LlmProvider, effort: Effort = Effort.LOW) -> Any:
    return await provider.complete(
        model="m-test",
        system="You are a tutor.",
        messages=MESSAGES,
        output_schema=SCHEMA,
        max_output_tokens=500,
        effort=effort,
        timeout_seconds=5,
    )


def openai_response(
    content: list[dict[str, Any]],
    *,
    status: str = "completed",
    incomplete: str | None = None,
) -> Handler:
    payload = {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "gpt-test-2026-01-01",
        "status": status,
        "incomplete_details": {"reason": incomplete} if incomplete else None,
        "output": [
            {"type": "reasoning", "id": "rs_1", "summary": []},
            {"type": "message", "id": "msg_1", "role": "assistant", "status": status,
             "content": content},
        ],
        "usage": {
            "input_tokens": 120, "output_tokens": 30, "total_tokens": 150,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 10},
        },
        "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
    }  # fmt: skip
    return lambda _req: httpx2.Response(200, json=payload)


def text(value: str) -> dict[str, Any]:
    return {"type": "output_text", "text": value, "annotations": []}


async def test_openai_sends_strict_schema_effort_and_no_storage() -> None:
    rec = Recorder(openai_response([text('{"reply": "Which function is inside?"}')]))
    result = await call(openai_provider(rec), Effort.HIGH)

    assert result.text == '{"reply": "Which function is inside?"}'
    assert (result.input_tokens, result.output_tokens) == (120, 30)
    assert result.model_version == "gpt-test-2026-01-01"
    body = rec.body
    assert rec.requests[-1].url.path.endswith("/responses")
    assert body["model"] == "m-test"
    assert body["instructions"] == "You are a tutor."
    assert [m["role"] for m in body["input"]] == ["user", "assistant", "user"]
    assert body["reasoning"] == {"effort": "high"}
    assert body["max_output_tokens"] == 500
    assert body["store"] is False
    assert body["text"]["format"] == {
        "type": "json_schema", "name": "output", "schema": SCHEMA, "strict": True,
    }  # fmt: skip


async def test_openai_refusal_is_not_an_answer() -> None:
    rec = Recorder(openai_response([{"type": "refusal", "refusal": "I can't help."}]))
    with pytest.raises(ProviderRefusalError) as err:
        await call(openai_provider(rec))
    assert err.value.input_tokens == 120  # still charged to the budget


async def test_openai_max_tokens_is_truncation() -> None:
    rec = Recorder(
        openai_response(
            [text('{"reply": "Wh')], status="incomplete", incomplete="max_output_tokens"
        )
    )
    with pytest.raises(ProviderTruncatedError):
        await call(openai_provider(rec))


async def test_openai_content_filter_is_a_refusal() -> None:
    rec = Recorder(openai_response([], status="incomplete", incomplete="content_filter"))
    with pytest.raises(ProviderRefusalError):
        await call(openai_provider(rec))


@pytest.mark.parametrize(
    ("status", "expected"),
    [(429, ProviderTransientError), (503, ProviderTransientError),
     (400, ProviderPermanentError), (401, ProviderPermanentError)],
)  # fmt: skip
async def test_openai_http_errors_map_to_retry_policy(status: int, expected: type) -> None:
    rec = Recorder(lambda _r: httpx2.Response(status, json={"error": {"message": "x"}}))
    with pytest.raises(expected):
        await call(openai_provider(rec))
    assert len(rec.requests) == 1  # the SDK does not retry; the gateway owns retries


async def test_openai_connection_error_is_transient() -> None:
    def boom(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down", request=request)

    with pytest.raises(ProviderTransientError):
        await call(openai_provider(Recorder(boom)))


def anthropic_response(stop_reason: str, value: str) -> Handler:
    payload = {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-test",
        "content": [{"type": "text", "text": value}], "stop_reason": stop_reason,
        "stop_sequence": None, "usage": {"input_tokens": 90, "output_tokens": 20},
    }  # fmt: skip
    return lambda _req: httpx2.Response(200, json=payload)


async def test_anthropic_sends_schema_and_effort() -> None:
    rec = Recorder(anthropic_response("end_turn", '{"reply": "What is inside?"}'))
    result = await call(anthropic_provider(rec), Effort.MEDIUM)
    assert result.text == '{"reply": "What is inside?"}'
    assert result.model_version == "claude-test"
    body = rec.body
    assert body["system"] == "You are a tutor."
    assert body["output_config"] == {
        "effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA},
    }  # fmt: skip


@pytest.mark.parametrize(
    ("stop", "expected"),
    [("refusal", ProviderRefusalError), ("max_tokens", ProviderTruncatedError)],
)
async def test_anthropic_stop_reasons(stop: str, expected: type) -> None:
    with pytest.raises(expected):
        await call(anthropic_provider(Recorder(anthropic_response(stop, "{}"))))


def test_factory_picks_the_configured_provider(clean_env: pytest.MonkeyPatch) -> None:
    def settings(name: ProviderName) -> Settings:
        return Settings(_env_file=None, llm_provider=name)  # type: ignore[call-arg]

    clean_env.setenv("OPENAI_API_KEY", "sk-test-not-real")
    clean_env.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")
    assert isinstance(real_llm_provider(settings(ProviderName.OPENAI)), OpenAIProvider)
    assert isinstance(real_llm_provider(settings(ProviderName.ANTHROPIC)), AnthropicProvider)
    with pytest.raises(ConfigError):
        real_llm_provider(settings(ProviderName.MOCK))
