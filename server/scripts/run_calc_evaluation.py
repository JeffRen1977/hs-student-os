"""Run the Calc BC evaluation cases through the real grading pipeline (Step 21).

    HSOS_LLM_PROVIDER=anthropic|openai (key in ANTHROPIC_API_KEY / OPENAI_API_KEY or .env) \\
        uv run python -m scripts.run_calc_evaluation --out content/evaluation/calc_bc/report-v1.md

Each case goes through the same SkillExecutor → LLMGateway → rubric-assessment skill →
server-side evidence derivation used in production, and is compared with its human
annotation. Thresholds come only from `dimensions.json`; a dimension without a reviewer-set
threshold is reported as "not gated", never as passing. Reviewer-rated dimensions (evidence
quality, feedback usefulness) are left for the reviewer to fill in.

This costs money and refuses to run without a real provider: synthetic output is never
grading evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.adapters.firestore.memory_store import MemoryDocumentStore
from app.adapters.firestore.unit_of_work import DocumentUnitOfWork
from app.adapters.llm.gateway import Gateway
from app.adapters.llm.provider import LlmProvider
from app.adapters.runtime import RandomIdFactory, SystemClock
from app.adapters.tools.math_verify import MathVerifyTool
from app.bootstrap import model_router, real_llm_provider
from app.config import LlmProvider as LlmProviderName
from app.config import Settings
from app.domain.assessment_service import derive_skill_evidence
from app.domain.budget import BudgetLedger, BudgetLimits
from app.domain.ports.execution import ExecutionFailure, ExecutionRequest
from app.domain.skill_executor import SkillExecutor
from app.domain.types.assessment import AssessmentStatus, EvidenceObservation
from app.domain.types.run import Run, RunKind, RunStatus
from app.domain.types.session import (
    ContextVersion,
    Session,
    SessionActivity,
    SessionStatus,
    completion_for,
)
from app.domain.types.submission import Submission, SubmissionAnswer
from app.registries.content import ContentRegistry, load_content
from app.registries.course_catalog import RegistryCourseCatalog
from app.registries.evaluation import EvaluationSet, load_evaluation_set
from app.registries.subject_pack_registry import ContentSubjectPackRegistry
from app.registries.tool_registry import ToolRegistry
from app.schemas.evaluation import AssessmentEvaluationCase

COURSE_ID = "calc_bc"


@dataclass(slots=True)
class CaseResult:
    case_id: str
    category: str
    expected_status: str
    model_status: str
    criteria_matched: int
    criteria_total: int
    evidence_ok: bool
    hint_tracking_ok: bool | None  # only judged for cases with server hints
    tokens: int
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvaluationRun:
    results: list[CaseResult]
    model_version: str
    pack_version: str
    workflow_version: str

    def rate(self, numerator: int, denominator: int) -> str:
        return (
            f"{numerator}/{denominator} ({numerator / denominator:.0%})" if denominator else "n/a"
        )

    @property
    def rubric_accuracy(self) -> str:
        matched = sum(r.criteria_matched for r in self.results)
        total = sum(r.criteria_total for r in self.results)
        return self.rate(matched, total)

    @property
    def false_acceptance(self) -> str:
        pool = [r for r in self.results if r.expected_status == "insufficient_evidence"]
        return self.rate(sum(r.model_status == "accepted" for r in pool), len(pool))

    @property
    def false_insufficient(self) -> str:
        pool = [r for r in self.results if r.expected_status == "accepted"]
        return self.rate(sum(r.model_status == "insufficient_evidence" for r in pool), len(pool))

    @property
    def hint_tracking(self) -> str:
        pool = [r for r in self.results if r.hint_tracking_ok is not None]
        return self.rate(sum(bool(r.hint_tracking_ok) for r in pool), len(pool))

    @property
    def mean_tokens(self) -> str:
        graded = [r.tokens for r in self.results if r.tokens]
        return f"{sum(graded) / len(graded):.0f} tokens" if graded else "n/a"


def build_executor(
    provider: LlmProvider, settings: Settings, content: ContentRegistry
) -> SkillExecutor:
    clock, ids = SystemClock(), RandomIdFactory()
    ledger = BudgetLedger(
        DocumentUnitOfWork(MemoryDocumentStore()),
        clock,
        ids,
        BudgetLimits(
            run_tokens=settings.llm_run_token_budget,
            session_tokens=settings.llm_session_token_budget,
            daily_tokens=settings.llm_daily_token_budget,
        ),
    )
    gateway = Gateway(
        provider,
        model_router(settings),
        ledger,
        max_attempts=settings.llm_max_attempts,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    packs = ContentSubjectPackRegistry(content)
    return SkillExecutor(gateway, packs, ToolRegistry([MathVerifyTool()]), clock, ids)


def _request(case: AssessmentEvaluationCase, content: ContentRegistry) -> ExecutionRequest:
    packs = ContentSubjectPackRegistry(content)
    pack = packs.pack(COURSE_ID)
    question = packs.question(COURSE_ID, case.question_ref.question_id)
    course = RegistryCourseCatalog(content).get(COURSE_ID)
    assert pack and question and course
    now = datetime.now(UTC)
    session = Session(
        session_id=f"eval_{case.case_id}",
        student_id="stu_eval",
        task_id="task_eval",
        course_id=COURSE_ID,
        status=SessionStatus.OPEN,
        active_run_id="run_eval",
        context_version=ContextVersion(pack=pack.pack_version, workflow=pack.workflow_version),
        completion=completion_for(SessionStatus.OPEN, "run_eval", False),
        version=1,
        agent_skills=tuple(course.skills),
        activity=SessionActivity(
            question_id=question.question_id,
            question_version=question.version,
            rubric_id=question.rubric_id,
            rubric_version=question.rubric_version,
        ),
    )
    submission = Submission(
        submission_id="sub_eval",
        student_id="stu_eval",
        session_id=session.session_id,
        question_id=question.question_id,
        question_version=question.version,
        answer=SubmissionAnswer(text=case.student_answer.text),
        supersedes_submission_id=None,
        run_id="run_eval",
        created_at=now,
        server_hint_count=case.session_context.server_hint_count,
    )
    run = Run(
        run_id="run_eval",
        student_id="stu_eval",
        session_id=session.session_id,
        status=RunStatus.RUNNING,
        kind=RunKind.ASSESS_SUBMISSION,
        submission_id="sub_eval",
        attempt_count=1,
    )
    return ExecutionRequest(
        run=run,
        session=session,
        course=course,
        student_text=submission.answer.text,
        submission=submission,
        student_name="Student",
        mode="GPA_SYNC",
    )


async def evaluate(
    executor: SkillExecutor, evaluation: EvaluationSet, content: ContentRegistry
) -> EvaluationRun:
    packs = ContentSubjectPackRegistry(content)
    pack = packs.pack(COURSE_ID)
    assert pack is not None
    results: list[CaseResult] = []
    model_versions: set[str] = set()
    for case in evaluation.assessment_cases:
        expected = {r.criterion_id: r.earned for r in case.expected.rubric_results}
        request = _request(case, content)
        try:
            output = await executor.execute(request)
        except ExecutionFailure as exc:
            results.append(
                CaseResult(
                    case_id=case.case_id,
                    category=case.category,
                    expected_status=case.expected.status.value,
                    model_status=f"FAILED:{exc.code}",
                    criteria_matched=0,
                    criteria_total=len(expected),
                    evidence_ok=False,
                    hint_tracking_ok=None,
                    tokens=0,
                    notes=[exc.code],
                )
            )
            continue
        draft = output.assessment
        assert draft is not None
        model_versions.add(draft.model_version)
        question = packs.question(COURSE_ID, draft.question_id)
        rubric = packs.rubric(COURSE_ID, draft.rubric_id, draft.rubric_version)
        assert question and rubric
        evidence = (
            derive_skill_evidence(
                question,
                rubric,
                draft.rubric_results,
                assisted=request.submission is not None and request.submission.is_assisted,
            )
            if draft.status is AssessmentStatus.ACCEPTED
            else []
        )
        hinted = case.session_context.server_hint_count > 0
        notes = list(draft.uncertainty.reasons)
        expected_evidence = {(e.skill_id, e.observation) for e in case.expected.skill_evidence}
        actual_evidence = {(e.skill_id, e.observation) for e in evidence}
        if expected_evidence != actual_evidence:
            notes.append("skill evidence differs from annotation")
        results.append(
            CaseResult(
                case_id=case.case_id,
                category=case.category,
                expected_status=case.expected.status.value,
                model_status=draft.status.value,
                criteria_matched=sum(
                    r.earned == expected.get(r.criterion_id) for r in draft.rubric_results
                ),
                criteria_total=len(expected),
                evidence_ok=all(r.evidence_refs for r in draft.rubric_results if r.earned),
                hint_tracking_ok=(
                    all(
                        e.observation is not EvidenceObservation.CORRECT_INDEPENDENT
                        for e in evidence
                    )
                    if hinted
                    else None
                ),
                tokens=output.usage_tokens,
                notes=notes,
            )
        )
    return EvaluationRun(
        results=results,
        model_version=", ".join(sorted(model_versions)) or "none",
        pack_version=pack.pack_version,
        workflow_version=pack.workflow_version,
    )


def _threshold(evaluation: EvaluationSet, dimension_id: str) -> tuple[str, str, str]:
    for d in evaluation.dimensions.dimensions:
        if d.dimension_id == dimension_id:
            if d.threshold is None:
                return "not set", "—", "not gated"
            return str(d.threshold), str(d.threshold_set_by), "compare manually"
    return "unknown", "—", "not gated"


def render_report(
    run: EvaluationRun, evaluation: EvaluationSet, content: ContentRegistry, *, operator: str
) -> str:
    pack = content.pack(COURSE_ID)
    assert pack is not None
    cases_reviewed = all(c.review.status == "reviewed" for c in evaluation.assessment_cases)
    content_reviewed = all(q.review.status == "reviewed" for q in pack.questions.values()) and all(
        r.review.status == "reviewed" for r in pack.rubrics.values()
    )
    n = len(run.results)

    def row(name: str, arrow: str, dimension_id: str, result: str) -> str:
        threshold, by, verdict = _threshold(evaluation, dimension_id)
        return f"| {name} | {arrow} | {threshold} | {by} | {result} | {verdict} |"

    def box(ok: bool) -> str:
        return "x" if ok else " "

    lines = [
        f"# Learning Evaluation Report — {COURSE_ID} — v1",
        "",
        "> Generated by `scripts/run_calc_evaluation.py`. Sample size is small "
        f"(n = {n} cases); treat every rate as indicative, not as a measured quality level.",
        "",
        "## 1. Run identification",
        "",
        "| Field | Value |",
        "|---|---|",
        "| Report version | 1 |",
        f"| Date (UTC) | {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} |",
        f"| Evaluation set | `content/evaluation/{COURSE_ID}/` ({n} cases) |",
        "| Prerequisite set | not run (prerequisite consumers arrive in M3) |",
        f"| Pack / rubric versions | {run.pack_version} / per-question rubric v1 |",
        f"| Workflow version | {run.workflow_version} |",
        f"| Model + version | {run.model_version} |",
        "| Provider mode | real |",
        f"| Operator | {operator} |",
        "",
        "## 2. Content gate",
        "",
        f"- [{box(cases_reviewed)}] Every case has `review.status = reviewed` "
        "with a named reviewer",
        f"- [{box(content_reviewed)}] Every question and rubric referenced is `reviewed`",
        "- [x] No College Board official items used without a license (all items original)",
        "- [x] No real student data in any case (all answers synthetic)",
        "",
        "## 3. Results by dimension",
        "",
        "| Dimension | Direction | Threshold (from dimensions.json) | Set by | Result "
        "| Pass/Fail |",
        "|---|---|---|---|---|---|",
        row("Rubric accuracy", "↑", "rubric-accuracy", run.rubric_accuracy),
        row(
            "Evidence quality",
            "↑",
            "evidence-quality",
            "reviewer rating pending (structural check per case below)",
        ),
        row("False acceptance rate", "↓", "false-acceptance-rate", run.false_acceptance),
        row("False insufficient rate", "↓", "false-insufficient-rate", run.false_insufficient),
        row("Hint-dependency tracking", "↑", "hint-dependency-tracking", run.hint_tracking),
        row("Feedback usefulness", "↑", "feedback-usefulness", "reviewer rating pending"),
        row("Prerequisite precision", "↑", "prerequisite-precision", "not run (M3)"),
        "",
        "A dimension with no reviewer-set threshold is reported as **not gated**, not as passing.",
        f"Mean model usage per graded case: {run.mean_tokens} (retries included).",
        "",
        "## 4. Per-case results",
        "",
        "| Case ID | Category | Expected status | Model status | Criteria matched | Evidence OK "
        "| Hint tracking OK | Feedback (1–4) | Notes |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in run.results:
        hint = "n/a" if r.hint_tracking_ok is None else ("yes" if r.hint_tracking_ok else "NO")
        lines.append(
            f"| {r.case_id} | {r.category} | {r.expected_status} | {r.model_status} | "
            f"{r.criteria_matched}/{r.criteria_total} | {'yes' if r.evidence_ok else 'NO'} | "
            f"{hint} | (reviewer) | {'; '.join(r.notes) or '—'} |"
        )
    lines += [
        "",
        "## 5. Prerequisite cases",
        "",
        "Not run: prerequisite mapping and consumers are M3 (Steps 22–24).",
        "",
        "## 6. Failures and scope decisions",
        "",
        "To be completed by the reviewer for every mismatch above (fix, narrow scope, or "
        "accept with justification).",
        "",
        "## 7. Sign-off",
        "",
        "| Role | Name | Date | Decision |",
        "|---|---|---|---|",
        "| Content reviewer | | | approve / reject |",
        "| Engineering owner | | | approve / reject |",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--operator", default=os.environ.get("USER", "unknown"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    settings = Settings()
    if settings.llm_provider is LlmProviderName.MOCK:
        print("Refusing to evaluate with a mock provider: set HSOS_LLM_PROVIDER=anthropic|openai.")
        return 2
    if args.out.exists() and not args.overwrite:
        print(f"{args.out} exists; pass --overwrite to replace it.")
        return 2
    content = load_content()
    evaluation = load_evaluation_set(COURSE_ID)
    executor = build_executor(real_llm_provider(settings), settings, content)
    run = asyncio.run(evaluate(executor, evaluation, content))
    args.out.write_text(render_report(run, evaluation, content, operator=args.operator))
    print(f"Wrote {args.out} ({len(run.results)} cases).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
