"""Internal tool registry: `execute(name, input, context)` (Step 17.4, BACKEND.md §7).

A tool runs only if it is registered, whitelisted for the calling skill, *and* declared in
the course pack's manifest. Inputs are checked against the tool's parameter schema. Tool
failures come back as a non-OK status: they are never raised past here and never turned
into a fabricated success.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from app.domain.ports.tools import ToolContext, ToolNotAllowedError, ToolOutcome
from app.domain.types.tool import ToolStatus

logger = logging.getLogger(__name__)

SKILL_TOOL_WHITELIST: Mapping[str, frozenset[str]] = {
    "rubric-assessment": frozenset({"math-verify"}),
    "socratic-guidance": frozenset(),
}


class Tool(Protocol):
    name: str

    def validate(self, tool_input: Mapping[str, object]) -> dict[str, Any]:
        """Return the normalized input or raise ValueError."""
        ...

    async def run(self, tool_input: Mapping[str, Any]) -> ToolOutcome: ...


class ToolRegistry:
    def __init__(
        self,
        tools: Sequence[Tool],
        whitelist: Mapping[str, frozenset[str]] = SKILL_TOOL_WHITELIST,
    ) -> None:
        self._tools = {t.name: t for t in tools}
        self._whitelist = whitelist

    async def execute(
        self, name: str, tool_input: Mapping[str, object], context: ToolContext
    ) -> ToolOutcome:
        tool = self._tools.get(name)
        if (
            tool is None
            or name not in self._whitelist.get(context.skill, frozenset())
            or name not in context.pack_tools
        ):
            raise ToolNotAllowedError(f"{name} is not available to {context.skill}")
        try:
            validated = tool.validate(tool_input)
        except ValueError:
            return ToolOutcome(tool=name, status=ToolStatus.INVALID_INPUT, output={})
        try:
            outcome = await tool.run(validated)
        except Exception as exc:  # a broken tool must not break or fake the run
            logger.warning("tool_failed", extra={"tool": name, "error": type(exc).__name__,
                                                 "runId": context.run_id})  # fmt: skip
            return ToolOutcome(tool=name, status=ToolStatus.ERROR, output={})
        logger.info("tool_executed", extra={"tool": name, "status": outcome.status.value,
                                            "runId": context.run_id})  # fmt: skip
        return outcome
