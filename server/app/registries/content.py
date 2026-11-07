"""Load, cross-validate and serve versioned course content.

Two sources feed one registry:

- **Bundled packs** in `server/content/packs/` (Calc BC and the planned catalog entries),
  loaded at startup.
- **Authored packages** (course package contract v1, Step 26) that went through the
  validator and a platform reviewer. They are installed from the package store by
  `PackageContentSync` and may have several servable versions: the active one plus older
  versions that open sessions and past assessments are pinned to.

Validation is two-level: each item must satisfy its Pydantic schema, and references
between items (question → rubric, rubric/question → skill, ability → data) must resolve.
`pack_issues` returns *every* problem with a path; a course never references another
course's skills or content.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.domain.types.common import Availability
from app.domain.types.package import PackageIssue
from app.schemas.content import (
    Material,
    PackManifest,
    Question,
    Rubric,
    SkillCatalog,
)
from app.schemas.package import EvaluationCase, StarterTask

DEFAULT_CONTENT_ROOT = Path(__file__).resolve().parents[2] / "content"

# The platform ability and tool catalogs (CLAUDE.md §3.5): a package selects from these;
# a missing capability becomes a new platform ability, never course code.
ABILITY_CATALOG = frozenset(
    {"socratic-guidance", "rubric-assessment", "choice-scoring", "source-analysis"}
)
SOURCE_ANALYSIS = "source-analysis"
TOOL_CATALOG = frozenset({"math-verify", "content-retrieval"})


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
    starter_tasks: list[StarterTask] = field(default_factory=list)
    practice_sequence: list[StarterTask] = field(default_factory=list)
    evaluation_set: list[EvaluationCase] = field(default_factory=list)
    authored: bool = False  # True when the pack came from a reviewed course package

    @property
    def is_active(self) -> bool:
        return self.manifest.availability is Availability.ACTIVE

    @property
    def is_retired(self) -> bool:
        return self.manifest.availability is Availability.RETIRED

    @property
    def skill_ids(self) -> set[str]:
        return {s.skill_id for s in self.skills.skills} if self.skills else set()

    def with_availability(self, availability: Availability) -> Pack:
        return Pack(
            manifest=self.manifest.model_copy(update={"availability": availability}),
            skills=self.skills,
            questions=self.questions,
            rubrics=self.rubrics,
            system_prompt=self.system_prompt,
            materials=self.materials,
            starter_tasks=self.starter_tasks,
            practice_sequence=self.practice_sequence,
            evaluation_set=self.evaluation_set,
            authored=self.authored,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AuthoredVersion:
    """A servable authored version and whether it is its course's current version."""

    pack: Pack
    current: bool  # the course's active version, or its retired one
    retired: bool = False


class ContentRegistry:
    """Every course's current pack plus every servable version (for pinned lookups).

    Authored packages are swapped in as a whole by `install_authored`, so readers always
    see one consistent snapshot.
    """

    def __init__(self, packs: Mapping[str, Pack]) -> None:
        self._bundled = dict(packs)
        self.packs: dict[str, Pack] = dict(packs)
        self._versions: dict[tuple[str, str], Pack] = {
            (cid, p.manifest.version): p for cid, p in packs.items()
        }

    @property
    def bundled_course_ids(self) -> frozenset[str]:
        return frozenset(self._bundled)

    def install_authored(self, versions: Iterable[AuthoredVersion]) -> None:
        packs = dict(self._bundled)
        all_versions = {(cid, p.manifest.version): p for cid, p in self._bundled.items()}
        for v in versions:
            cid = v.pack.manifest.course_id
            if cid in self._bundled:
                continue  # bundled course ids are reserved; never shadowed by a package
            all_versions[(cid, v.pack.manifest.version)] = v.pack
            if v.current:
                packs[cid] = v.pack.with_availability(
                    Availability.RETIRED if v.retired else Availability.ACTIVE
                )
        self.packs = packs
        self._versions = all_versions

    def pack(self, course_id: str) -> Pack | None:
        return self.packs.get(course_id)

    def pack_version(self, course_id: str, version: str | None) -> Pack | None:
        """`version=None` → the current pack; otherwise that exact (pinned) version."""
        if version is None:
            return self.packs.get(course_id)
        return self._versions.get((course_id, version))

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


# ---- Cross-reference checks (shared by bundled packs and authored packages) ---------------


def _issue(path: str, code: str, message: str) -> PackageIssue:
    return PackageIssue(path=path, code=code, message=message)


def pack_issues(pack: Pack) -> list[PackageIssue]:
    """Every cross-reference problem of a pack, each with a path. Empty → consistent."""
    issues: list[PackageIssue] = []
    m = pack.manifest
    cid = m.course_id
    abilities, tools = set(m.skills), set(m.tools)
    for a in sorted(abilities - ABILITY_CATALOG):
        issues.append(_issue("manifest.abilities", "unknown_ability", f"unknown ability {a}"))
    for t in sorted(tools - TOOL_CATALOG):
        issues.append(_issue("manifest.tools", "unknown_tool", f"unknown tool {t}"))
    if pack.is_active and not pack.questions:
        issues.append(
            _issue("questions", "empty", f"{cid}: active packs need at least one question")
        )

    known_skills = pack.skill_ids
    if pack.skills is not None:
        if pack.skills.course_id != cid:
            issues.append(_issue("skills", "course_mismatch", "skills: courseId mismatch"))
        for s in sorted(known_skills):
            if not s.startswith(cid + "."):
                issues.append(
                    _issue(
                        f"skills[{s}]",
                        "skill_prefix",
                        "skillIds must be prefixed with the courseId",
                    )
                )

    for (rid, ver), rubric in sorted(pack.rubrics.items()):
        path = f"rubrics[{rid}@{ver}]"
        if rubric.course_id != cid:
            issues.append(
                _issue(f"{path}.courseId", "course_mismatch", f"rubric {rid}: courseId mismatch")
            )
        for c in rubric.criteria:
            unknown = sorted(set(c.skill_ids) - known_skills)
            if unknown:
                issues.append(
                    _issue(
                        f"{path}.criteria[{c.criterion_id}].skillIds",
                        "unknown_skill",
                        f"rubric {rid}: unknown skills {unknown}",
                    )
                )

    has_choice = has_free = has_sourced = False
    for qid, q in sorted(pack.questions.items()):
        path = f"questions[{qid}]"
        if q.course_id != cid:
            issues.append(
                _issue(f"{path}.courseId", "course_mismatch", f"question {qid}: courseId mismatch")
            )
        unknown = sorted(set(q.skill_ids) - known_skills)
        if unknown:
            issues.append(
                _issue(
                    f"{path}.skillIds", "unknown_skill", f"question {qid}: unknown skills {unknown}"
                )
            )
        ref = q.rubric_ref
        q_rubric = pack.rubrics.get((ref.rubric_id, ref.version))
        if q_rubric is None:
            issues.append(
                _issue(
                    f"{path}.rubricRef",
                    "missing_rubric",
                    f"question {qid}: missing rubric {ref.rubric_id}@{ref.version}",
                )
            )
            continue
        criteria = {c.criterion_id for c in q_rubric.criteria}
        if q.answer_check is not None:
            if q.answer_check.criterion_id not in criteria:
                issues.append(
                    _issue(
                        f"{path}.answerCheck",
                        "unknown_criterion",
                        f"question {qid}: answerCheck criterion not in rubric",
                    )
                )
            if q.answer_check.tool not in tools:
                issues.append(
                    _issue(
                        f"{path}.answerCheck.tool",
                        "tool_not_selected",
                        f"question {qid}: tool not in pack",
                    )
                )
        if q.items is not None:
            has_choice = True
            # Every item scores exactly one rubric criterion, and every criterion one item.
            if sorted(i.criterion_id for i in q.items) != sorted(criteria):
                issues.append(
                    _issue(
                        f"{path}.items",
                        "items_criteria_mismatch",
                        f"question {qid}: items and rubric criteria differ",
                    )
                )
            if "choice-scoring" not in abilities:
                issues.append(
                    _issue(
                        f"{path}.items",
                        "ability_not_selected",
                        f"question {qid}: pack cannot score items (needs choice-scoring)",
                    )
                )
        elif q.source_material_ids:
            # Source-based writing is graded by source-analysis against these documents.
            has_sourced = True
            for mid in q.source_material_ids:
                mat = pack.materials.get(mid)
                if mat is None or mat.course_id != cid:
                    issues.append(
                        _issue(
                            f"{path}.sourceMaterialIds",
                            "unknown_material",
                            f"question {qid}: unknown source material {mid}",
                        )
                    )
            if SOURCE_ANALYSIS not in abilities:
                issues.append(
                    _issue(
                        path,
                        "ability_not_selected",
                        f"question {qid}: source-based questions need source-analysis",
                    )
                )
        else:
            has_free = True
            if pack.authored and "rubric-assessment" not in abilities:
                issues.append(
                    _issue(
                        path,
                        "ability_not_selected",
                        f"question {qid}: free-response questions need rubric-assessment",
                    )
                )

    # An ability selected without the data it needs is rejected here, not at runtime.
    if pack.authored:
        if "choice-scoring" in abilities and not has_choice:
            issues.append(
                _issue(
                    "manifest.abilities",
                    "ability_without_data",
                    "choice-scoring needs at least one choice set",
                )
            )
        if "rubric-assessment" in abilities and not has_free:
            issues.append(
                _issue(
                    "manifest.abilities",
                    "ability_without_data",
                    "rubric-assessment needs at least one free-response question",
                )
            )
        if SOURCE_ANALYSIS in abilities and not has_sourced:
            issues.append(
                _issue(
                    "manifest.abilities",
                    "ability_without_data",
                    "source-analysis needs at least one question with sourceMaterialIds",
                )
            )

    for mid, mat in sorted(pack.materials.items()):
        path = f"materials[{mid}]"
        if mat.course_id != cid:
            issues.append(
                _issue(f"{path}.courseId", "course_mismatch", f"material {mid}: courseId mismatch")
            )
        unknown = sorted(set(mat.skill_ids) - known_skills)
        if unknown:
            issues.append(
                _issue(
                    f"{path}.skillIds", "unknown_skill", f"material {mid}: unknown skills {unknown}"
                )
            )

    seen_starters: set[str] = set()
    sequence = [("starterTasks", i, st) for i, st in enumerate(pack.starter_tasks)]
    sequence += [("practiceSequence", i, st) for i, st in enumerate(pack.practice_sequence)]
    for field_name, i, st in sequence:
        path = f"{field_name}[{i}]"
        if st.question_id not in pack.questions:
            issues.append(
                _issue(
                    f"{path}.questionId", "unknown_question", f"unknown question {st.question_id}"
                )
            )
        if st.question_id in seen_starters:
            issues.append(
                _issue(
                    f"{path}.questionId",
                    "duplicate",
                    "a question appears once in starterTasks and practiceSequence",
                )
            )
        seen_starters.add(st.question_id)
        if st.task_type not in m.supported_task_types:
            issues.append(
                _issue(
                    f"{path}.taskType",
                    "unsupported_task_type",
                    "taskType not in supportedTaskTypes",
                )
            )
        if st.mode not in m.supported_modes:
            issues.append(_issue(f"{path}.mode", "unsupported_mode", "mode not in supportedModes"))

    case_ids: set[str] = set()
    for case in pack.evaluation_set:
        path = f"evaluationSet[{case.case_id}]"
        if case.case_id in case_ids:
            issues.append(_issue(path, "duplicate", "caseId values must be unique"))
        case_ids.add(case.case_id)
        case_q = pack.questions.get(case.question_id)
        if case_q is None:
            issues.append(
                _issue(
                    f"{path}.questionId", "unknown_question", f"unknown question {case.question_id}"
                )
            )
            continue
        case_rubric = pack.rubrics.get((case_q.rubric_ref.rubric_id, case_q.rubric_ref.version))
        if case_rubric is None or case.expected_status != "accepted":
            continue
        limits = {c.criterion_id: c.max_points for c in case_rubric.criteria}
        if set(case.expected_earned) != set(limits):
            issues.append(
                _issue(
                    f"{path}.expectedEarned",
                    "criteria_mismatch",
                    "expectedEarned must list every rubric criterion",
                )
            )
        for crit, pts in sorted(case.expected_earned.items()):
            if crit in limits and not 0 <= pts <= limits[crit]:
                issues.append(
                    _issue(
                        f"{path}.expectedEarned.{crit}",
                        "out_of_range",
                        "points outside 0..maxPoints",
                    )
                )
    return issues


# ---- Bundled packs (disk) -------------------------------------------------------------------


def _load_pack(directory: Path) -> Pack:
    manifest = _parse(PackManifest, directory / "manifest.json")
    if manifest.course_id != directory.name:
        raise ContentError(f"{directory}: courseId {manifest.course_id} != directory name")
    pack = Pack(manifest=manifest)

    skills_path = directory / "skills.json"
    if skills_path.exists():
        pack.skills = _parse(SkillCatalog, skills_path)

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

    issues = pack_issues(pack)
    if issues:
        raise ContentError(f"{directory}: " + "; ".join(f"{i.path}: {i.message}" for i in issues))
    return pack


def load_content(root: Path = DEFAULT_CONTENT_ROOT) -> ContentRegistry:
    packs: dict[str, Pack] = {}
    for directory in sorted(p for p in (root / "packs").iterdir() if p.is_dir()):
        pack = _load_pack(directory)
        packs[pack.manifest.course_id] = pack
    return ContentRegistry(packs)
