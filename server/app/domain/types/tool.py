from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ToolStatus(StrEnum):
    """A tool result never claims more than the tool established."""

    OK = "ok"  # the tool ran and produced `output`
    UNAVAILABLE = "unavailable"  # dependency missing or timed out: no verification happened
    INVALID_INPUT = "invalid_input"  # input rejected by the tool's parameter schema
    ERROR = "error"  # the tool failed while running


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolResult:
    """One entry in a run's tool ledger. Inputs are not stored (they may hold student work)."""

    tool_result_id: str
    student_id: str
    run_id: str
    tool: str
    status: ToolStatus
    output: Mapping[str, object] = field(default_factory=dict)
    created_at: datetime | None = None
