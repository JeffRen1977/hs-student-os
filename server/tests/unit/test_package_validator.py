"""Course package contract v1: the validator returns every error with its path (Step 26.2).

The Digital SAT package (content/authored/dsat) is the reference valid package; each test
breaks one thing and checks the error path and code an author would see.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from app.registries.content import DEFAULT_CONTENT_ROOT
from app.registries.package_validator import validate_package

DSAT = json.loads((DEFAULT_CONTENT_ROOT / "authored/dsat/package.json").read_text())


@pytest.fixture
def pkg() -> dict[str, Any]:
    return copy.deepcopy(DSAT)


def errors(raw: dict[str, Any]) -> set[tuple[str, str]]:
    return {(e.path, e.code) for e in validate_package(raw).report.errors}


def question(pkg: dict[str, Any], qid: str) -> dict[str, Any]:
    return next(q for q in pkg["questions"] if q["questionId"] == qid)


def test_reference_package_is_valid_and_its_evaluation_set_passes() -> None:
    checked = validate_package(DSAT)
    assert checked.report.valid, checked.report.errors
    ev = checked.report.evaluation
    assert (ev.auto_cases, ev.auto_passed, ev.model_cases) == (12, 12, 0)
    assert checked.pack is not None and checked.pack.authored
    assert (checked.course_id, checked.version) == ("dsat", "1.0.0")
    # Same content → same hash, whatever the key order of the upload.
    reordered = json.loads(json.dumps(DSAT, sort_keys=True))
    assert validate_package(reordered).content_hash == checked.content_hash


def test_schema_errors_are_all_reported_with_paths(pkg: dict[str, Any]) -> None:
    del pkg["manifest"]["license"]
    pkg["manifest"]["modelTier"] = "huge"
    pkg["questions"][1]["source"] = {"type": "original"}
    pkg["surprise"] = True
    found = errors(pkg)
    assert ("manifest.license", "missing") in found
    assert ("manifest.modelTier", "literal_error") in found
    assert ("questions[1].source.author", "missing") in found
    assert ("surprise", "extra_forbidden") in found  # unknown fields are rejected
    assert validate_package(pkg).pack is None


def test_a_package_cannot_reference_another_courses_skills(pkg: dict[str, Any]) -> None:
    question(pkg, "q_dsat_equiv_001")["skillIds"] = ["calc_bc.chain-rule"]
    pkg["rubrics"][0]["criteria"][0]["skillIds"] = ["calc_bc.chain-rule"]
    found = errors(pkg)
    assert ("questions[q_dsat_equiv_001].skillIds", "unknown_skill") in found
    assert ("rubrics[dsat-equiv-001@1].criteria[item-1].skillIds", "unknown_skill") in found


def test_items_must_belong_to_the_manifest_course(pkg: dict[str, Any]) -> None:
    question(pkg, "q_dsat_nonlin_001")["courseId"] = "calc_bc"
    pkg["skills"].append({"skillId": "calc_bc.x", "name": "x", "description": "x"})
    found = errors(pkg)
    assert ("questions[q_dsat_nonlin_001].courseId", "course_mismatch") in found
    assert ("skills[calc_bc.x]", "skill_prefix") in found


def test_dangling_references_are_rejected(pkg: dict[str, Any]) -> None:
    question(pkg, "q_dsat_equiv_002")["rubricRef"] = {"rubricId": "missing", "version": "1"}
    pkg["starterTasks"][0]["questionId"] = "q_missing"
    pkg["evaluationSet"][0]["questionId"] = "q_missing"
    found = errors(pkg)
    assert ("questions[q_dsat_equiv_002].rubricRef", "missing_rubric") in found
    assert ("starterTasks[0].questionId", "unknown_question") in found
    assert (
        f"evaluationSet[{pkg['evaluationSet'][0]['caseId']}].questionId",
        "unknown_question",
    ) in found


def test_only_platform_abilities_and_tools(pkg: dict[str, Any]) -> None:
    pkg["manifest"]["abilities"].append("essay-grader")
    pkg["manifest"]["tools"].append("web-search")
    found = errors(pkg)
    assert ("manifest.abilities", "unknown_ability") in found
    assert ("manifest.tools", "unknown_tool") in found


def test_an_ability_without_its_data_is_rejected_at_validation(pkg: dict[str, Any]) -> None:
    # rubric-assessment needs free-response questions; this package has only choice sets.
    pkg["manifest"]["abilities"].append("rubric-assessment")
    assert ("manifest.abilities", "ability_without_data") in errors(pkg)


def test_free_response_questions_need_rubric_assessment(pkg: dict[str, Any]) -> None:
    q = question(pkg, "q_dsat_equiv_002")
    del q["items"]
    rubric = next(r for r in pkg["rubrics"] if r["rubricId"] == q["rubricRef"]["rubricId"])
    assert rubric
    pkg["evaluationSet"] = [c for c in pkg["evaluationSet"] if c["questionId"] != q["questionId"]]
    assert ("questions[q_dsat_equiv_002]", "ability_not_selected") in errors(pkg)


def test_starter_tasks_use_supported_types_and_modes(pkg: dict[str, Any]) -> None:
    pkg["starterTasks"][0]["taskType"] = "FRQ_PRACTICE"
    pkg["starterTasks"][1]["mode"] = "EXAM_CRUNCH"
    found = errors(pkg)
    assert ("starterTasks[0].taskType", "unsupported_task_type") in found
    assert ("starterTasks[1].mode", "unsupported_mode") in found


def test_system_prompt_may_use_only_platform_variables(pkg: dict[str, Any]) -> None:
    pkg["systemPrompt"] += "\nAnswer key: {{answerKey}}"
    assert ("systemPrompt", "unknown_template_variable") in errors(pkg)


def test_evaluation_expectations_must_match_the_rubric(pkg: dict[str, Any]) -> None:
    case = pkg["evaluationSet"][0]
    case["expectedEarned"] = {"item-1": 5}
    found = errors(pkg)
    assert (f"evaluationSet[{case['caseId']}].expectedEarned", "criteria_mismatch") in found
    assert (f"evaluationSet[{case['caseId']}].expectedEarned.item-1", "out_of_range") in found


def test_a_failing_evaluation_case_is_reported_not_hidden(pkg: dict[str, Any]) -> None:
    # Well-formed, but the expectation is wrong: the platform runs the case and says so.
    case = pkg["evaluationSet"][0]
    case["expectedEarned"] = {k: 0 for k in case["expectedEarned"]}
    report = validate_package(pkg).report
    assert report.valid
    assert report.evaluation.failures == (case["caseId"],)
    assert not report.evaluation.auto_all_passed


def test_oversized_package_is_rejected(pkg: dict[str, Any]) -> None:
    pkg["systemPrompt"] = "x" * 950_000
    assert errors(pkg) == {("$", "too_large")}


def test_duplicate_ids_are_rejected(pkg: dict[str, Any]) -> None:
    pkg["questions"].append(copy.deepcopy(pkg["questions"][0]))
    assert (f"questions[{len(pkg['questions']) - 1}]", "duplicate") in errors(pkg)
