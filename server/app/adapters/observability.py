"""Structured logs and log-based metrics (Step 31.1–31.2).

Logs are one JSON object per line in the shape Cloud Logging parses (`severity`,
`message`, plus fields). Privacy rule (CLAUDE.md §6.4): log ids, model tier, latency,
tokens, retries and error codes, never answers, drafts, essays, tokens or tool payloads.
The formatter enforces it instead of trusting every call site:

- numbers and booleans pass under any key (they cannot carry text);
- strings, lists and dicts pass only under `SAFE_KEYS`; anything else becomes
  "[redacted]", and strings are capped at 200 characters;
- exceptions are logged as type plus stack frames (file, line, function), never the
  exception message, which can echo input (e.g. validation errors quote the payload).

Metrics are emitted as `metric` log entries (`LogMetrics`); Cloud Monitoring log-based
metrics and alert policies are defined on them in `deploy/monitoring/`.
"""

from __future__ import annotations

import json
import logging
import sys
import time
import traceback
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request, Response

from app.domain.ports.metrics import Metrics

SAFE_KEYS = frozenset(
    {
        "requestId", "runId", "studentId", "actorId", "sessionId", "deliveryId",
        "assessmentId", "planId", "reminderId", "kind", "status", "error", "errorCode",
        "reason", "tool", "tier", "modelTier", "model", "modelVersion", "provider",
        "package", "channel", "metric", "labels", "alert", "route", "method", "event",
        "service", "outcome", "scope",
    }
)  # fmt: skip
MAX_STRING = 200
_STANDARD = frozenset(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}
REDACTED = "[redacted]"


def _safe(key: str, value: Any) -> Any:
    if isinstance(value, bool | int | float) or value is None:
        return value
    if key not in SAFE_KEYS:
        return REDACTED
    if isinstance(value, str):
        return value[:MAX_STRING]
    if isinstance(value, dict):
        return {str(k): _safe(key, v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_safe(key, v) for v in value][:50]
    return REDACTED


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.msg if isinstance(record.msg, str) else REDACTED,
            "logger": record.name,
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                entry[key] = _safe(key, value)
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, _, tb = record.exc_info
            entry["exception"] = {
                "type": exc_type.__name__,
                "frames": [
                    f"{f.filename.rsplit('/', 1)[-1]}:{f.lineno}:{f.name}"
                    for f in traceback.extract_tb(tb)
                ][-15:],
            }
        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger once (API and worker processes)."""
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonLogFormatter) for h in root.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    root.addHandler(handler)
    root.setLevel(level)


_metrics_logger = logging.getLogger("app.metrics")


class LogMetrics:
    """One `metric` log entry per measurement, for Cloud Monitoring log-based metrics."""

    def count(self, name: str, value: int = 1, **labels: str) -> None:
        _metrics_logger.info("metric", extra={"metric": name, "value": value, "labels": labels})

    def observe(self, name: str, value: float, **labels: str) -> None:
        _metrics_logger.info("metric", extra={"metric": name, "value": value, "labels": labels})


class InMemoryMetrics:
    """Test double: totals per (name, sorted labels) and every observation."""

    def __init__(self) -> None:
        self.counts: dict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)
        self.observations: dict[str, list[float]] = defaultdict(list)

    def count(self, name: str, value: int = 1, **labels: str) -> None:
        self.counts[(name, tuple(sorted(labels.items())))] += value

    def observe(self, name: str, value: float, **labels: str) -> None:
        self.observations[name].append(value)

    def total(self, name: str, **labels: str) -> int:
        return sum(
            v
            for (n, ls), v in self.counts.items()
            if n == name and all(dict(ls).get(k) == lv for k, lv in labels.items())
        )


def install_request_metrics(app: FastAPI, metrics: Callable[[], Metrics]) -> None:
    """Latency and status class per route template; idempotent replays are counted as
    duplicate suppression. The raw path (which contains ids) is not used as a label."""

    @app.middleware("http")
    async def _measure(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.monotonic()
        response = await call_next(request)
        route = getattr(request.scope.get("route"), "path", "unmatched")
        sink = metrics()
        sink.observe(
            "http.latency_ms",
            round((time.monotonic() - started) * 1000, 1),
            route=route,
            method=request.method,
            status=f"{response.status_code // 100}xx",
        )
        if response.headers.get("Idempotency-Replayed") == "true":
            sink.count("duplicate.suppressed", source="idempotency", route=route)
        return response
