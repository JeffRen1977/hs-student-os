"""The `choice-scoring` platform ability: parsing and content validation (pure)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.domain.skills.choice_scoring import parse_choices
from app.registries.content import DEFAULT_CONTENT_ROOT
from app.registries.package_validator import validate_package
from app.schemas.content import Question

DSAT_PACKAGE = DEFAULT_CONTENT_ROOT / "authored/dsat/package.json"


def dsat_package() -> dict:  # type: ignore[type-arg]
    return json.loads(DSAT_PACKAGE.read_text())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1: B\n2: c\n3: A", {"1": "B", "2": "C", "3": "A"}),
        ("1. B\n2) C\nItem 3 - (a)", {"1": "B", "2": "C", "3": "A"}),
        ("B C A", {}),
        ("1: B\n1: C", None),  # an item answered twice is unreadable
    ],
)
def test_parse_choices(text: str, expected: dict[str, str] | None) -> None:
    parsed = parse_choices(text)
    assert (None if parsed is None else {k: v.choice for k, v in parsed.items()}) == expected


def test_choice_items_need_a_valid_answer_key() -> None:
    [raw] = [q for q in dsat_package()["questions"] if q["questionId"] == "q_dsat_equiv_001"]
    bad_key = {
        **raw,
        "items": [{**raw["items"][0], "answerKey": "D", "choices": raw["items"][0]["choices"][:3]}],
    }
    with pytest.raises(ValidationError):
        Question.model_validate(bad_key)
    with pytest.raises(ValidationError):  # cross-course diagnostic specs no longer exist
        Question.model_validate({**raw, "diagnostic": {"targetSkillId": "dsat.x"}})


def test_a_pack_with_choice_items_must_select_choice_scoring() -> None:
    package = dsat_package()
    package["manifest"]["abilities"] = ["socratic-guidance"]
    report = validate_package(package).report
    assert not report.valid
    assert {e.code for e in report.errors} == {"ability_not_selected"}
    assert all(e.path.startswith("questions[q_dsat_") for e in report.errors)
