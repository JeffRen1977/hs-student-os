"""Step 38.3: core workflows run without any optional infrastructure.

doc/OPTIONAL_INFRASTRUCTURE.md assesses Jev, MCP adapters, Temporal and semantic indexes;
none is adopted. This test keeps it that way until a deliberate decision: no optional
package is a runtime dependency, and the app plus a full learning loop run with those
modules made unimportable.
"""

from __future__ import annotations

import builtins
import importlib
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

OPTIONAL_MODULES = (
    "temporalio", "mcp", "jev", "langchain", "llama_index", "chromadb", "faiss",
    "pinecone", "weaviate", "qdrant_client", "pgvector", "sentence_transformers",
)  # fmt: skip
PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_no_optional_package_is_a_runtime_dependency() -> None:
    deps = tomllib.loads(PYPROJECT.read_text())["project"]["dependencies"]
    names = {d.split("[")[0].split(">")[0].split("=")[0].split("<")[0].strip().lower()
             .replace("-", "_") for d in deps}  # fmt: skip
    assert not names & set(OPTIONAL_MODULES)


async def test_core_loop_runs_with_optional_modules_unimportable(
    clean_env: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def guarded(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.split(".")[0] in OPTIONAL_MODULES:
            raise ImportError(f"optional module {name} is not installed (test)")
        return real_import(name, *args, **kwargs)

    clean_env.setattr(builtins, "__import__", guarded)
    for mod in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        clean_env.delitem(sys.modules, mod)
    importlib.import_module("app.main")

    from tests.support import build_harness  # imports the app under the guard

    h = build_harness(clean_env)
    assert (await h.client.get("/api/health")).status_code == 200
    # A key-scored Digital SAT practice set: session → submission → run → assessment.
    r = await h.client.post("/api/sessions", json={"taskId": "task_alex_dsat_01"},
                            headers=h.cmd("stu_alex"))  # fmt: skip
    session = r.json()
    act = session["activity"]
    r = await h.client.post(
        f"/api/sessions/{session['sessionId']}/submissions",
        json={"questionId": act["questionId"], "questionVersion": act["questionVersion"],
              "answer": {"text": "1: A\n2: C\n3: B"}},
        headers=h.cmd("stu_alex"),
    )  # fmt: skip
    assert r.status_code == 202
    await h.settle()
    run = (await h.client.get(f"/api/runs/{r.json()['runId']}", headers=h.auth("stu_alex"))).json()
    assert run["status"] == "SUCCEEDED" and run["result"]["assessmentId"]
