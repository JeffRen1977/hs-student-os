"""Step 21: the evaluation runner's comparison and report logic.

Uses a scripted provider replaying the annotations, so it validates the *runner*, not any
model. Real results come only from running the script against a real provider.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.registries.content import load_content
from app.registries.evaluation import load_evaluation_set
from scripts.run_calc_evaluation import build_executor, evaluate, main, render_report
from tests.support import ScriptedProvider
from tests.unit.test_skills import scripted_grade


async def test_runner_compares_against_annotations(clean_env: pytest.MonkeyPatch) -> None:
    content, evaluation = load_content(), load_evaluation_set("calc_bc")
    cases = evaluation.assessment_cases
    replies = [scripted_grade(c) for c in cases]
    # Make one case disagree: accept the insufficient-work case.
    ibp = next(i for i, c in enumerate(cases) if c.case_id == "eval-calc-insufficient-work-ibp")
    replies[ibp]["status"] = "accepted"
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    executor = build_executor(ScriptedProvider(*replies), settings, content)
    run = await evaluate(executor, evaluation, content)

    assert len(run.results) == len(cases)
    assert run.rubric_accuracy.startswith(f"{sum(r.criteria_total for r in run.results)}/")
    assert run.false_acceptance == "1/2 (50%)"  # the deliberate disagreement is caught
    assert run.false_insufficient == "0/4 (0%)"
    assert run.hint_tracking == "1/1 (100%)"
    report = render_report(run, evaluation, content, operator="test")
    assert "not gated" in report and "Provider mode | real" in report
    assert "- [ ] Every case has `review.status = reviewed`" in report  # drafts not hidden
    assert f"n = {len(cases)} cases" in report


def test_runner_refuses_mock_provider(clean_env: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    assert main(["--out", str(out)]) == 2
    assert not out.exists()
