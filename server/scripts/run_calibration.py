"""Run the mastery calibration check (Step 37) on held-out responses and write a report.

    uv run python -m scripts.run_calibration --course calc_bc \\
        --input held_out.jsonl --out content/evaluation/calc_bc/calibration-v1.md [--synthetic]

Input: one JSON object per line with studentRef (pseudonymous), courseId, skillId,
levelBefore, correct, independent, source (held_out | practice | self_reported). No names,
emails or answers: calibration needs none. `--synthetic` marks the run as a pipeline test;
a synthetic report can never support a prediction.

The report states the calibration status and what the prediction gate decides. It never
writes a prediction anywhere: predictions stay `unavailable` (CLAUDE.md §1.3).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.domain.calibration import (
    CalibrationReport,
    CalibrationResponse,
    PredictionEvidence,
    ResponseSource,
    calibrate,
    decide_prediction,
)
from app.domain.types.student import MasteryLevel
from app.registries.content import load_content

FORBIDDEN_FIELDS = {"name", "email", "answer", "answerText", "studentId"}


def read_responses(path: Path) -> list[CalibrationResponse]:
    out: list[CalibrationResponse] = []
    for n, line in enumerate(path.read_text("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if leaked := FORBIDDEN_FIELDS & set(row):
            raise SystemExit(f"line {n}: identifying fields are not accepted: {sorted(leaked)}")
        out.append(
            CalibrationResponse(
                student_ref=str(row["studentRef"]),
                course_id=str(row["courseId"]),
                skill_id=str(row["skillId"]),
                level_before=MasteryLevel(row["levelBefore"]),
                correct=bool(row["correct"]),
                independent=bool(row["independent"]),
                source=ResponseSource(row["source"]),
            )
        )
    return out


def render(report: CalibrationReport) -> str:
    decision = decide_prediction(report.course_id, PredictionEvidence(calibration=report))
    data = "**synthetic (pipeline test, not evidence)**" if report.synthetic else "held-out"
    lines = [
        f"# Mastery calibration — {report.course_id}",
        "",
        f"- Data: {data}",
        f"- Status: **{report.status.value}**"
        + (f" ({', '.join(report.reasons)})" if report.reasons else ""),
        f"- Responses used: {report.responses_used} from {report.students} students; "
        f"skill coverage {report.skill_coverage:.0%}",
        f"- Excluded: {report.excluded or 'none'}",
        f"- Accuracy rises with level: {'yes' if report.monotonic else 'no'}; "
        f"Brier score {report.brier if report.brier is not None else 'n/a'}",
        f"- Exam prediction: **{decision.status.value}** ({decision.reason})",
        "",
        "| Mastery level | Held-out responses | Accuracy |",
        "|---|---|---|",
    ]
    for lv in report.levels:
        acc = f"{lv.accuracy:.2f}" if lv.accuracy is not None else "—"
        lines.append(f"| {lv.level.value} | {lv.responses} | {acc} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--course", required=True)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args(argv)
    content = load_content()
    pack = content.packs.get(args.course)
    if pack is None:
        raise SystemExit(f"unknown course {args.course}")
    report = calibrate(
        args.course, pack.skill_ids, read_responses(args.input), synthetic=args.synthetic
    )
    text = render(report)
    if args.out:
        args.out.write_text(text, "utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
