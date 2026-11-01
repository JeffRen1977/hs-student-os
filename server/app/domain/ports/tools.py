from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from app.domain.types.tool import ToolStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolContext:
    """Who is calling and from where. Tools are whitelisted per skill and per pack."""

    student_id: str
    course_id: str
    run_id: str
    skill: str
    pack_tools: Sequence[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolOutcome:
    tool: str
    status: ToolStatus
    output: Mapping[str, object]


class ToolNotAllowedError(Exception):
    pass


class ToolRunner(Protocol):
    async def execute(
        self, name: str, tool_input: Mapping[str, object], context: ToolContext
    ) -> ToolOutcome:
        """Raises ToolNotAllowedError for tools outside the skill/pack whitelist. Tool
        failures are returned as a non-OK status, never raised and never reported as OK."""
        ...
