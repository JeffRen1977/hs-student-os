"""Load and cross-validate versioned content from `server/content/`.

Validation is two-level: each file must satisfy its Pydantic schema, and references
between files (question → rubric, rubric/question → skill, mapping → skill) must resolve.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.domain.types.common import Availability
from app.schemas.content import (
    Material,
    PackManifest,
    PrerequisiteMappingSet,
    Question,
    Rubric,
    SkillCatalog,
)

DEFAULT_CONTENT_ROOT = Path(__file__).resolve().parents[2] / "content"


class ContentError(ValueError):
    pass


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _parse[M: BaseModel](model: type[M], path: Path) -> M:
    try:
        return model.model_validate(load_json(path))
    except (ValidationError, json.JSONDecodeError) as exc:
        raise ContentError(f"{path}: {exc}") from exc


@dataclass(slots=True)
class Pack:
    manifest: PackManifest
    skills: SkillCatalog | None = None
    questions: dict[str, Question] = field(default_factory=dict)
    rubrics: dict[tuple[str, str], Rubric] = field(default_factory=dict)
    system_prompt: str | None = None
    materials: dict[str, Material] = field(default_factory=dict)

    @property
    def is_active(self) -> bool:
        return self.manifest.availability is Availability.ACTIVE

    @property
    def skill_ids(self) -> set[str]:
        return {s.skill_id for s in self.skills.skills} if self.skills else set()


@dataclass(slots=True)
class ContentRegistry:
    packs: dict[str, Pack]
    mapping_sets: dict[str, PrerequisiteMappingSet]

    def pack(self, course_id: str) -> Pack | None:
        return self.packs.get(course_id)

    def active_course_ids(self) -> set[str]:
        return {cid for cid, pack in self.packs.items() if pack.is_active}

    def all_skill_ids(self) -> set[str]:
        return set().union(*(p.skill_ids for p in self.packs.values()))

    def rubric(self, rubric_id: str, version: str) -> Rubric | None:
        for pack in self.packs.values():
            if (rubric_id, version) in pack.rubrics:
                return pack.rubrics[(rubric_id, version)]
        return None

    def question(self, question_id: str) -> Question | None:
        for pack in self.packs.values():
            if question_id in pack.questions:
                return pack.questions[question_id]
        return None


def _load_pack(directory: Path) -> Pack:
    manifest = _parse(PackManifest, directory / "manifest.json")
    if manifest.course_id != directory.name:
        raise ContentError(f"{directory}: courseId {manifest.course_id} != directory name")
    pack = Pack(manifest=manifest)

    skills_path = directory / "skills.json"
    if skills_path.exists():
        pack.skills = _parse(SkillCatalog, skills_path)
        if pack.skills.course_id != manifest.course_id:
            raise ContentError(f"{skills_path}: courseId mismatch")
        if not all(s.startswith(manifest.course_id + ".") for s in pack.skill_ids):
            raise ContentError(f"{skills_path}: skillIds must be prefixed with the courseId")

    if manifest.system_prompt_path:
        prompt_path = directory / manifest.system_prompt_path
        if not prompt_path.is_file():
            raise ContentError(f"{directory}: missing {manifest.system_prompt_path}")
        pack.system_prompt = prompt_path.read_text(encoding="utf-8")

    for path in sorted((directory / "rubrics").glob("*.json")):
        rubric = _parse(Rubric, path)
        key = (rubric.rubric_id, rubric.version)
        if key in pack.rubrics:
            raise ContentError(f"{path}: duplicate rubric {key}")
        pack.rubrics[key] = rubric

    for path in sorted((directory / "questions").glob("*.json")):
        question = _parse(Question, path)
        if question.question_id in pack.questions:
            raise ContentError(f"{path}: duplicate questionId {question.question_id}")
        pack.questions[question.question_id] = question

    for path in sorted((directory / "materials").glob("*.json")):
        material = _parse(Material, path)
        if material.material_id in pack.materials:
            raise ContentError(f"{path}: duplicate materialId {material.material_id}")
        pack.materials[material.material_id] = material

    _check_pack_references(pack)
    return pack


def _check_pack_references(pack: Pack) -> None:
    cid = pack.manifest.course_id
    if pack.is_active and not pack.questions:
        raise ContentError(f"{cid}: active packs need at least one question")
    known_skills = pack.skill_ids
    for rubric in pack.rubrics.values():
        if rubric.course_id != cid:
            raise ContentError(f"rubric {rubric.rubric_id}: courseId mismatch")
        for criterion in rubric.criteria:
            unknown = set(criterion.skill_ids) - known_skills
            if unknown:
                raise ContentError(f"rubric {rubric.rubric_id}: unknown skills {unknown}")
    for question in pack.questions.values():
        if question.course_id != cid:
            raise ContentError(f"question {question.question_id}: courseId mismatch")
        unknown = set(question.skill_ids) - known_skills
        if unknown:
            raise ContentError(f"question {question.question_id}: unknown skills {unknown}")
        ref = question.rubric_ref
        if (ref.rubric_id, ref.version) not in pack.rubrics:
            raise ContentError(
                f"question {question.question_id}: missing rubric {ref.rubric_id}@{ref.version}"
            )
        check = question.answer_check
        if check is not None:
            rubric = pack.rubrics[(ref.rubric_id, ref.version)]
            if check.criterion_id not in {c.criterion_id for c in rubric.criteria}:
                raise ContentError(
                    f"question {question.question_id}: answerCheck criterion not in rubric"
                )
            if check.tool not in pack.manifest.tools:
                raise ContentError(f"question {question.question_id}: tool not in pack")
    for material in pack.materials.values():
        if material.course_id != cid:
            raise ContentError(f"material {material.material_id}: courseId mismatch")
        unknown = set(material.skill_ids) - known_skills
        if unknown:
            raise ContentError(f"material {material.material_id}: unknown skills {unknown}")


def load_content(root: Path = DEFAULT_CONTENT_ROOT) -> ContentRegistry:
    packs: dict[str, Pack] = {}
    for directory in sorted(p for p in (root / "packs").iterdir() if p.is_dir()):
        pack = _load_pack(directory)
        packs[pack.manifest.course_id] = pack

    registry = ContentRegistry(packs=packs, mapping_sets={})
    all_skills = registry.all_skill_ids()
    for path in sorted((root / "mappings").glob("*.json")):
        mapping_set = _parse(PrerequisiteMappingSet, path)
        for course in (mapping_set.source_course_id, mapping_set.target_course_id):
            if course not in packs:
                raise ContentError(f"{path}: unknown course {course}")
        for mapping in mapping_set.mappings:
            for skill in (mapping.source_skill_id, mapping.target_skill_id):
                if skill not in all_skills:
                    raise ContentError(f"{path}: unknown skill {skill}")
            if not mapping.source_skill_id.startswith(mapping_set.source_course_id + "."):
                raise ContentError(f"{path}: {mapping.mapping_id} source is not in source course")
            if not mapping.target_skill_id.startswith(mapping_set.target_course_id + "."):
                raise ContentError(f"{path}: {mapping.mapping_id} target is not in target course")
        registry.mapping_sets[mapping_set.mapping_set_id] = mapping_set
    return registry
