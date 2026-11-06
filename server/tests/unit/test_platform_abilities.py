"""Step 34.2 and 34.5: adding a platform ability is checked at validation time, and every
existing course still validates and passes its key-scored evaluation set afterwards."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from app.registries.content import ABILITY_CATALOG, DEFAULT_CONTENT_ROOT, load_content, pack_issues
from app.registries.package_validator import validate_package

AUTHORED = sorted(p.parent.name for p in (DEFAULT_CONTENT_ROOT / "authored").glob("*/package.json"))
APUSH = json.loads((DEFAULT_CONTENT_ROOT / "authored/apush/package.json").read_text())


def apush(**edits: Any) -> dict[str, Any]:
    pkg = copy.deepcopy(APUSH)
    for fn in edits.values():
        fn(pkg)
    return pkg


def codes(pkg: dict[str, Any]) -> set[str]:
    return {e.code for e in validate_package(pkg).report.errors}


def dbq(pkg: dict[str, Any]) -> dict[str, Any]:
    return next(q for q in pkg["questions"] if q["questionId"] == "q_apush_dbq_001")


def test_source_analysis_is_a_platform_ability() -> None:
    assert "source-analysis" in ABILITY_CATALOG


@pytest.mark.parametrize("course", AUTHORED)
def test_every_authored_course_still_validates_and_passes_its_key_scored_cases(
    course: str,
) -> None:
    raw = json.loads((DEFAULT_CONTENT_ROOT / f"authored/{course}/package.json").read_text())
    report = validate_package(raw).report
    assert report.valid, report.errors
    assert report.evaluation.auto_all_passed and not report.evaluation.failures


def test_bundled_courses_are_unaffected_by_the_new_ability() -> None:
    content = load_content()
    for cid in content.bundled_course_ids:
        assert pack_issues(content.packs[cid]) == []
    # Calc BC never selected source-analysis and has no sourced questions.
    calc = content.packs["calc_bc"]
    assert "source-analysis" not in calc.manifest.skills
    assert all(not q.source_material_ids for q in calc.questions.values())


def test_sourced_question_needs_the_ability() -> None:
    def drop(pkg: dict[str, Any]) -> None:
        pkg["manifest"]["abilities"].remove("source-analysis")

    assert "ability_not_selected" in codes(apush(drop=drop))


def test_ability_without_a_sourced_question_is_rejected() -> None:
    def unsource(pkg: dict[str, Any]) -> None:
        dbq(pkg)["sourceMaterialIds"] = []
        pkg["evaluationSet"] = [c for c in pkg["evaluationSet"] if "dbq" not in c["caseId"]]

    assert "ability_without_data" in codes(apush(unsource=unsource))


def test_unknown_source_material_is_rejected() -> None:
    def ghost(pkg: dict[str, Any]) -> None:
        dbq(pkg)["sourceMaterialIds"].append("mat_does_not_exist")

    assert "unknown_material" in codes(apush(ghost=ghost))


def test_choice_sets_cannot_have_sources() -> None:
    def mix(pkg: dict[str, Any]) -> None:
        mc = next(q for q in pkg["questions"] if q["questionId"] == "q_apush_mc_001")
        mc["sourceMaterialIds"] = ["mat_apush_doc_a_federalist10"]

    assert "value_error" in codes(apush(mix=mix))
