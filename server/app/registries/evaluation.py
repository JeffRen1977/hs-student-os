"""Load the learning-evaluation baseline (`content/evaluation/`)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.registries.content import DEFAULT_CONTENT_ROOT, load_json
from app.schemas.evaluation import (
    AssessmentEvaluationCase,
    EvaluationDimensions,
    PrerequisiteEvaluationCase,
)


@dataclass(frozen=True, slots=True)
class EvaluationSet:
    assessment_cases: list[AssessmentEvaluationCase]
    prerequisite_cases: list[PrerequisiteEvaluationCase]
    dimensions: EvaluationDimensions


def load_evaluation_set(course_id: str, root: Path = DEFAULT_CONTENT_ROOT) -> EvaluationSet:
    base = root / "evaluation"
    return EvaluationSet(
        assessment_cases=[
            AssessmentEvaluationCase.model_validate(load_json(p))
            for p in sorted((base / course_id).glob("*.json"))
        ],
        prerequisite_cases=[
            PrerequisiteEvaluationCase.model_validate(load_json(p))
            for p in sorted((base / "prerequisites").glob("*.json"))
        ],
        dimensions=EvaluationDimensions.model_validate(load_json(base / "dimensions.json")),
    )
