"""The `choice-scoring` platform ability: parsing and content validation (pure)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.skills.choice_scoring import parse_choices
from app.registries.content import DEFAULT_CONTENT_ROOT, ContentError, load_content
from app.schemas.content import Question

CONTENT = load_content()


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
    raw = CONTENT.packs["dsat"].questions["q_dsat_equiv_001"].model_dump(by_alias=True)
    bad_key = {
        **raw,
        "items": [{**raw["items"][0], "answerKey": "D", "choices": raw["items"][0]["choices"][:3]}],
    }
    with pytest.raises(ValidationError):
        Question.model_validate(bad_key)
    with pytest.raises(ValidationError):  # cross-course diagnostic specs no longer exist
        Question.model_validate({**raw, "diagnostic": {"targetSkillId": "dsat.x"}})


def test_a_pack_with_choice_items_must_select_choice_scoring(tmp_path: Path) -> None:
    root = tmp_path / "content"
    shutil.copytree(DEFAULT_CONTENT_ROOT, root)
    path = root / "packs/dsat/manifest.json"
    manifest = json.loads(path.read_text())
    manifest["skills"] = ["socratic-guidance"]
    path.write_text(json.dumps(manifest))
    with pytest.raises(ContentError, match="cannot score items"):
        load_content(root)
