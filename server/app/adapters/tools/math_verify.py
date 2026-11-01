"""math-verify: symbolic equivalence of two expressions (Step 17.4, optional SymPy adapter).

SymPy's `parse_expr` evaluates Python, so input is locked down before it gets there: a
short character whitelist, no dunder/attribute access, identifiers limited to known math
functions plus the declared single-letter variables, and an empty builtins namespace.
Parsing and simplification run in a worker thread with a timeout. If SymPy is missing or
the check times out, the result is UNAVAILABLE: never a claimed success.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.domain.ports.tools import ToolOutcome
from app.domain.types.tool import ToolStatus

NAME = "math-verify"
MAX_LENGTH = 200
TIMEOUT_SECONDS = 3.0
_CHARS = re.compile(r"^[0-9a-zA-Z_+\-*/^().,\s]+$")
_ATTRIBUTE = re.compile(r"\.\s*[A-Za-z_]")  # "." only as a decimal point, never attribute access
_IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")
FUNCTIONS = frozenset(
    {"sin", "cos", "tan", "sec", "csc", "cot", "asin", "acos", "atan", "exp", "log", "ln",
     "sqrt", "pi", "E"}
)  # fmt: skip


def _check_expression(expr: object, variables: Sequence[str]) -> str:
    if not isinstance(expr, str) or not 0 < len(expr) <= MAX_LENGTH:
        raise ValueError("expression must be a non-empty string of at most 200 characters")
    if not _CHARS.fullmatch(expr) or "__" in expr or _ATTRIBUTE.search(expr):
        raise ValueError("expression contains disallowed characters")
    for ident in _IDENT.findall(expr):
        if ident not in FUNCTIONS and ident not in variables:
            raise ValueError("expression uses an unknown identifier")
    return expr


class MathVerifyTool:
    name = NAME

    def validate(self, tool_input: Mapping[str, object]) -> dict[str, Any]:
        if set(tool_input) != {"expression", "expected", "variables"}:
            raise ValueError("expected exactly: expression, expected, variables")
        variables = tool_input["variables"]
        if (
            not isinstance(variables, list)
            or not variables
            or not all(isinstance(v, str) and re.fullmatch(r"[a-z]", v) for v in variables)
        ):
            raise ValueError("variables must be single lowercase letters")
        return {
            "expression": _check_expression(tool_input["expression"], variables),
            "expected": _check_expression(tool_input["expected"], variables),
            "variables": list(variables),
        }

    async def run(self, tool_input: Mapping[str, Any]) -> ToolOutcome:
        try:
            import sympy  # noqa: F401
        except ImportError:
            return ToolOutcome(tool=NAME, status=ToolStatus.UNAVAILABLE, output={})
        try:
            equivalent = await asyncio.wait_for(
                asyncio.to_thread(_equivalent, tool_input), timeout=TIMEOUT_SECONDS
            )
        except TimeoutError:
            return ToolOutcome(tool=NAME, status=ToolStatus.UNAVAILABLE, output={})
        except (SyntaxError, TypeError, ValueError, ZeroDivisionError):
            return ToolOutcome(tool=NAME, status=ToolStatus.INVALID_INPUT, output={})
        return ToolOutcome(tool=NAME, status=ToolStatus.OK, output={"equivalent": equivalent})


def _equivalent(tool_input: Mapping[str, Any]) -> bool:
    import sympy
    from sympy.parsing.sympy_parser import (
        convert_xor,
        implicit_multiplication_application,
        parse_expr,
        standard_transformations,
    )

    namespace: dict[str, Any] = {
        "__builtins__": {},
        "Integer": sympy.Integer,
        "Float": sympy.Float,
        "Rational": sympy.Rational,
        "Symbol": sympy.Symbol,
        "Function": sympy.Function,
        "sin": sympy.sin, "cos": sympy.cos, "tan": sympy.tan, "sec": sympy.sec,
        "csc": sympy.csc, "cot": sympy.cot, "asin": sympy.asin, "acos": sympy.acos,
        "atan": sympy.atan, "exp": sympy.exp, "log": sympy.log, "ln": sympy.log,
        "sqrt": sympy.sqrt, "pi": sympy.pi, "E": sympy.E,
    }  # fmt: skip
    local = {v: sympy.Symbol(v) for v in tool_input["variables"]}
    transformations = (*standard_transformations, implicit_multiplication_application, convert_xor)

    def parse(text: str) -> Any:
        return parse_expr(
            text, local_dict=dict(local), global_dict=dict(namespace),
            transformations=transformations, evaluate=True,
        )  # fmt: skip

    difference = sympy.simplify(parse(tool_input["expression"]) - parse(tool_input["expected"]))
    return bool(difference == 0)
