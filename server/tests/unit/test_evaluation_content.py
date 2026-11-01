"""Step 7: the evaluation baseline is complete, consistent, and provenance-tracked.

This validates expected outcomes only. It does not evaluate any model.
"""

from __future__ import annotations

import pytest

from app.domain.types.assessment import AssessmentStatus, EvidenceObservation
from app.registries.content import ContentRegistry, load_content
from app.registries.evaluation import EvaluationSet, load_evaluation_set

REQUIRED_CATEGORIES = {
    "correct",
    "incorrect",
    "partial",
    "assisted",
    "ambiguous",
    "insufficient_work",
}


@pytest.fixture(scope="module")
def content() -> ContentRegistry:
    return load_content()


@pytest.fixture(scope="module")
def evaluation() -> EvaluationSet:
    return load_evaluation_set("calc_bc")


def test_all_required_categories_exist(evaluation: EvaluationSet) -> None:
    assert {c.category for c in evaluation.assessment_cases} >= REQUIRED_CATEGORIES


def test_cases_have_provenance_and_review_state(evaluation: EvaluationSet) -> None:
    for case in evaluation.assessment_cases:
        assert case.provenance.synthetic is True
        assert case.provenance.source.license
        assert case.review.status in {"draft", "reviewed"}
        assert case.rationale


def test_expected_rubric_results_match_rubric(
    evaluation: EvaluationSet, content: ContentRegistry
) -> None:
    for case in evaluation.assessment_cases:
        question = content.question(case.question_ref.question_id)
        assert question is not None and question.version == case.question_ref.version
        assert question.rubric_ref == case.rubric_ref
        rubric = content.rubric(case.rubric_ref.rubric_id, case.rubric_ref.version)
        assert rubric is not None
        max_points = {c.criterion_id: c.max_points for c in rubric.criteria}
        expected = {r.criterion_id: r.earned for r in case.expected.rubric_results}
        assert set(expected) == set(max_points), f"{case.case_id}: criteria must be complete"
        for criterion, earned in expected.items():
            assert earned <= max_points[criterion], f"{case.case_id}:{criterion}"
        for evidence in case.expected.skill_evidence:
            assert evidence.skill_id in question.skill_ids, case.case_id


def test_category_semantics(evaluation: EvaluationSet, content: ContentRegistry) -> None:
    for case in evaluation.assessment_cases:
        exp = case.expected
        rubric = content.rubric(case.rubric_ref.rubric_id, case.rubric_ref.version)
        assert rubric is not None
        total = sum(r.earned for r in exp.rubric_results)
        observations = {e.observation for e in exp.skill_evidence}
        hints = case.session_context.server_hint_count
        match case.category:
            case "correct":
                assert exp.status is AssessmentStatus.ACCEPTED and hints == 0
                assert total == rubric.max_points
                assert observations == {EvidenceObservation.CORRECT_INDEPENDENT}
            case "incorrect":
                assert exp.status is AssessmentStatus.ACCEPTED
                assert EvidenceObservation.INCORRECT in observations
            case "partial":
                assert exp.status is AssessmentStatus.ACCEPTED
                assert 0 < total < rubric.max_points
            case "assisted":
                assert exp.status is AssessmentStatus.ACCEPTED and hints > 0
                assert EvidenceObservation.CORRECT_WITH_HINT in observations
                assert EvidenceObservation.CORRECT_INDEPENDENT not in observations
            case "ambiguous" | "insufficient_work":
                assert exp.status is AssessmentStatus.INSUFFICIENT_EVIDENCE
                assert not exp.skill_evidence


def test_dimensions_have_no_invented_thresholds(evaluation: EvaluationSet) -> None:
    ids = {d.dimension_id for d in evaluation.dimensions.dimensions}
    assert {
        "rubric-accuracy",
        "evidence-quality",
        "false-acceptance-rate",
        "false-insufficient-rate",
        "hint-dependency-tracking",
        "feedback-usefulness",
    } <= ids
    for d in evaluation.dimensions.dimensions:
        if d.threshold is not None:
            assert d.threshold_set_by, f"{d.dimension_id} threshold needs a reviewer"
