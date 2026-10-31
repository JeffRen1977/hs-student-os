"""Step 4: versioned content packs, questions, rubrics, and prerequisite mappings."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.domain.types.common import Availability
from app.registries.content import DEFAULT_CONTENT_ROOT, ContentError, load_content


@pytest.fixture(scope="module")
def registry():  # type: ignore[no-untyped-def]
    return load_content()


def test_calc_bc_is_the_only_active_pack(registry) -> None:  # type: ignore[no-untyped-def]
    assert registry.active_course_ids() == {"calc_bc"}
    for cid in ("apush", "physics_c", "dsat"):
        pack = registry.pack(cid)
        assert pack is not None
        assert pack.manifest.availability is Availability.PLANNED
        assert not pack.is_active


def test_calc_bc_manifest(registry) -> None:  # type: ignore[no-untyped-def]
    m = registry.pack("calc_bc").manifest
    assert m.version == "1.0.0"
    assert m.supported_task_types and m.supported_modes
    assert registry.pack("calc_bc").system_prompt


def test_question_bank(registry) -> None:  # type: ignore[no-untyped-def]
    questions = registry.pack("calc_bc").questions
    assert 5 <= len(questions) <= 8
    for q in questions.values():
        assert q.version and q.source.license and q.review.status
        assert registry.rubric(q.rubric_ref.rubric_id, q.rubric_ref.version) is not None
        assert q.source.type == "original"


def test_content_is_draft_until_reviewed(registry) -> None:  # type: ignore[no-untyped-def]
    # Nobody has reviewed this content yet; it must not claim otherwise.
    pack = registry.pack("calc_bc")
    for item in [*pack.questions.values(), *pack.rubrics.values()]:
        assert item.review.status == "draft"
        assert item.review.reviewer is None


def test_rubric_criteria_cover_question_skills(registry) -> None:  # type: ignore[no-untyped-def]
    pack = registry.pack("calc_bc")
    for q in pack.questions.values():
        rubric = pack.rubrics[(q.rubric_ref.rubric_id, q.rubric_ref.version)]
        rubric_skills = {s for c in rubric.criteria for s in c.skill_ids}
        assert set(q.skill_ids) <= rubric_skills, q.question_id


def test_prerequisite_mappings(registry) -> None:  # type: ignore[no-untyped-def]
    mapping_set = registry.mapping_sets["calc-bc-to-dsat"]
    assert mapping_set.version
    for m in mapping_set.mappings:
        assert m.conditions and m.counterexamples
        assert m.status == "candidate"  # unreviewed mappings are candidates only
    sources = {m.source_skill_id for m in mapping_set.mappings}
    assert "calc_bc.lhopital" not in sources  # calculus-only skill: no SAT mapping


def _copy_content(tmp_path: Path) -> Path:
    root = tmp_path / "content"
    shutil.copytree(DEFAULT_CONTENT_ROOT, root)
    return root


def _edit(path: Path, **changes: object) -> None:
    data = json.loads(path.read_text())
    data.update(changes)
    path.write_text(json.dumps(data))


def test_dangling_rubric_reference_is_rejected(tmp_path: Path) -> None:
    root = _copy_content(tmp_path)
    _edit(
        root / "packs/calc_bc/questions/q_calc_bc_001.json",
        rubricRef={"rubricId": "missing", "version": "1"},
    )
    with pytest.raises(ContentError, match="missing rubric"):
        load_content(root)


def test_unknown_skill_is_rejected(tmp_path: Path) -> None:
    root = _copy_content(tmp_path)
    _edit(root / "packs/calc_bc/questions/q_calc_bc_001.json", skillIds=["calc_bc.made-up"])
    with pytest.raises(ContentError, match="unknown skills"):
        load_content(root)


def test_question_without_license_is_rejected(tmp_path: Path) -> None:
    root = _copy_content(tmp_path)
    _edit(root / "packs/calc_bc/questions/q_calc_bc_001.json", source={"type": "original"})
    with pytest.raises(ContentError):
        load_content(root)


def test_unlicensed_college_board_content_is_rejected(tmp_path: Path) -> None:
    root = _copy_content(tmp_path)
    _edit(
        root / "packs/calc_bc/questions/q_calc_bc_001.json",
        source={"type": "original", "author": "College Board", "license": "n/a"},
    )
    with pytest.raises(ContentError, match="College Board"):
        load_content(root)


def test_reviewed_status_requires_named_reviewer(tmp_path: Path) -> None:
    root = _copy_content(tmp_path)
    _edit(
        root / "packs/calc_bc/rubrics/calc-001.json",
        review={"status": "reviewed", "reviewer": None, "reviewedAt": None},
    )
    with pytest.raises(ContentError, match="reviewer"):
        load_content(root)


def test_mapping_without_counterexamples_is_rejected(tmp_path: Path) -> None:
    root = _copy_content(tmp_path)
    path = root / "mappings/calc-to-sat-prerequisites.json"
    data = json.loads(path.read_text())
    data["mappings"][0]["counterexamples"] = []
    path.write_text(json.dumps(data))
    with pytest.raises(ContentError):
        load_content(root)


def test_active_pack_must_be_complete(tmp_path: Path) -> None:
    root = _copy_content(tmp_path)
    _edit(root / "packs/apush/manifest.json", availability="active")
    with pytest.raises(ContentError, match="active packs require"):
        load_content(root)
