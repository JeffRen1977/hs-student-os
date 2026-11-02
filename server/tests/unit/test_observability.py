"""Step 31.1–31.2: structured logs never carry student content; metrics are recorded."""

from __future__ import annotations

import json
import logging

import pytest

from app.adapters.observability import REDACTED, JsonLogFormatter, LogMetrics


def render(record_fn: object = None, **extra: object) -> dict[str, object]:
    logger = logging.getLogger("test.obs")
    record = logger.makeRecord("test.obs", logging.INFO, __file__, 1, "run_finished", (), None,
                               extra=extra)  # fmt: skip
    return dict(json.loads(JsonLogFormatter().format(record)))


def test_ids_and_numbers_pass_and_free_text_is_redacted() -> None:
    entry = render(
        runId="run_1", studentId="stu_x", tokens=812, latencyMs=95.5, retries=1,
        modelTier="balanced", error="TimeoutError",
        answer="dy/dx = 3x^2", essayText="My essay", authToken="eyJ...", toolArgs={"x": 1},
    )  # fmt: skip
    assert entry["severity"] == "INFO" and entry["message"] == "run_finished"
    assert (entry["runId"], entry["tokens"], entry["latencyMs"]) == ("run_1", 812, 95.5)
    assert entry["modelTier"] == "balanced" and entry["error"] == "TimeoutError"
    for key in ("answer", "essayText", "authToken", "toolArgs"):
        assert entry[key] == REDACTED
    assert "3x^2" not in json.dumps(entry) and "eyJ" not in json.dumps(entry)


def test_exception_messages_are_not_logged() -> None:
    logger = logging.getLogger("test.obs")
    try:
        raise ValueError("student wrote: my secret answer")
    except ValueError:
        import sys

        record = logger.makeRecord(
            "test.obs", logging.ERROR, __file__, 1, "boom", (), sys.exc_info()
        )
    text = JsonLogFormatter().format(record)
    entry = json.loads(text)
    assert entry["exception"]["type"] == "ValueError"
    assert entry["exception"]["frames"]
    assert "secret" not in text


def test_long_safe_strings_are_capped() -> None:
    assert len(str(render(reason="x" * 5000)["reason"])) == 200


def test_log_metrics_emit_metric_entries(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.metrics")
    LogMetrics().count("duplicate.suppressed", source="delivery")
    [record] = caplog.records
    entry = json.loads(JsonLogFormatter().format(record))
    assert entry["metric"] == "duplicate.suppressed" and entry["value"] == 1
    assert entry["labels"] == {"source": "delivery"}
