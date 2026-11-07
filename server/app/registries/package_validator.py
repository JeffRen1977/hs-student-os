"""Course package validator v1 (Step 22.2 as needed by the review gate, Step 26).

`validate_package(raw)` never raises on bad input: it returns a report with *every* error
and the path where it occurs, so an author can fix a package in one pass. A package that
fails schema validation is not cross-checked further (its references cannot be trusted).

Checks, in order:
1. Schema: the `CoursePackage` contract, unknown fields rejected, size limit.
2. Identity: every question/rubric/material/skill belongs to the manifest's course.
3. References: question → rubric, rubric/question/material → skill, starter task and
   evaluation case → question, answer checks and choice items → rubric criteria.
4. Platform catalog: abilities and tools exist, and each selected ability has the data it
   needs (`choice-scoring` ↔ choice sets, `rubric-assessment` ↔ free-response questions,
   `source-analysis` ↔ questions with `sourceMaterialIds`, which must name course materials).
5. System prompt: only the platform's template variables may appear.
6. Evaluation set: cases on key-scored questions are run now, deterministically.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.domain.skills.choice_scoring import parse_choices
from app.domain.types.common import Availability
from app.domain.types.package import EvaluationSummary, PackageIssue, ValidationReport
from app.registries.content import Pack, pack_issues
from app.schemas.content import PackManifest, SkillCatalog
from app.schemas.package import MAX_PACKAGE_BYTES, CoursePackage, EvaluationCase

VALIDATOR_VERSION = "package-validator-v1"
TEMPLATE_VARIABLES = frozenset({"studentName", "currentMode", "masteryContext"})
_TEMPLATE = re.compile(r"\{\{\s*([^}]*?)\s*\}\}")


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidatedPackage:
    report: ValidationReport
    course_id: str | None
    version: str | None
    title: str
    canonical_json: str
    content_hash: str
    package: CoursePackage | None = None
    pack: Pack | None = None  # set only when the package is valid


def canonical_json(raw: Mapping[str, Any]) -> str:
    return json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _loc_path(loc: tuple[int | str, ...]) -> str:
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += ("." if out else "") + str(part)
    return out or "$"


def _schema_issues(exc: ValidationError) -> list[PackageIssue]:
    # Only locations and messages: submitted values are never echoed back.
    return [
        PackageIssue(path=_loc_path(tuple(e["loc"])), code=e["type"], message=e["msg"])
        for e in exc.errors(include_url=False, include_input=False)
    ]


def _identity(raw: Mapping[str, Any]) -> tuple[str | None, str | None, str]:
    manifest = raw.get("manifest") if isinstance(raw, Mapping) else None
    if not isinstance(manifest, Mapping):
        return None, None, ""
    cid, ver, name = manifest.get("courseId"), manifest.get("version"), manifest.get("name")
    return (
        cid if isinstance(cid, str) else None,
        ver if isinstance(ver, str) else None,
        name if isinstance(name, str) else "",
    )


def build_pack(pkg: CoursePackage) -> tuple[Pack, list[PackageIssue]]:
    """The runtime form of a package, plus duplicate-id issues found while indexing."""
    m = pkg.manifest
    issues: list[PackageIssue] = []
    manifest = PackManifest(
        course_id=m.course_id,
        name=m.name,
        description=m.description,
        category=m.category,
        version=m.version,
        availability=Availability.ACTIVE,
        agent_type=m.agent_type,
        supported_task_types=m.supported_task_types,
        supported_modes=m.supported_modes,
        skills=m.abilities,
        tools=m.tools,
        model_tier=m.model_tier,
        context_budget_tokens=m.context_budget_tokens,
        system_prompt_path="package:systemPrompt",
        workflow_version=m.workflow_version,
    )
    skill_ids = [s.skill_id for s in pkg.skills]
    for sid in sorted({s for s in skill_ids if skill_ids.count(s) > 1}):
        issues.append(
            PackageIssue(path=f"skills[{sid}]", code="duplicate", message="duplicate skillId")
        )
    pack = Pack(
        manifest=manifest,
        skills=SkillCatalog(course_id=m.course_id, version=m.version, skills=pkg.skills),
        system_prompt=pkg.system_prompt,
        starter_tasks=list(pkg.starter_tasks),
        practice_sequence=list(pkg.practice_sequence),
        evaluation_set=list(pkg.evaluation_set),
        authored=True,
    )
    for i, r in enumerate(pkg.rubrics):
        key = (r.rubric_id, r.version)
        if key in pack.rubrics:
            issues.append(
                PackageIssue(
                    path=f"rubrics[{i}]",
                    code="duplicate",
                    message=f"duplicate rubric {r.rubric_id}@{r.version}",
                )
            )
        pack.rubrics[key] = r
    for i, q in enumerate(pkg.questions):
        if q.question_id in pack.questions:
            issues.append(
                PackageIssue(
                    path=f"questions[{i}]",
                    code="duplicate",
                    message=f"duplicate questionId {q.question_id}",
                )
            )
        pack.questions[q.question_id] = q
    for i, mat in enumerate(pkg.materials):
        if mat.material_id in pack.materials:
            issues.append(
                PackageIssue(
                    path=f"materials[{i}]",
                    code="duplicate",
                    message=f"duplicate materialId {mat.material_id}",
                )
            )
        pack.materials[mat.material_id] = mat
    return pack, issues


def _prompt_issues(prompt: str) -> list[PackageIssue]:
    unknown = sorted({v for v in _TEMPLATE.findall(prompt) if v not in TEMPLATE_VARIABLES})
    return [
        PackageIssue(
            path="systemPrompt",
            code="unknown_template_variable",
            message=f"unknown template variable {{{{{v}}}}}; allowed: "
            + ", ".join(sorted(TEMPLATE_VARIABLES)),
        )
        for v in unknown
    ]


def _run_key_scored_case(pack: Pack, case: EvaluationCase) -> bool | None:
    """True/False for a key-scored case; None when the case needs model grading."""
    q = pack.questions[case.question_id]
    if q.items is None:
        return None
    rubric = pack.rubrics[(q.rubric_ref.rubric_id, q.rubric_ref.version)]
    parsed = parse_choices(case.answer_text)
    if parsed is None or set(parsed) != {i.item_id for i in q.items}:
        return case.expected_status == "insufficient_evidence"
    if case.expected_status != "accepted":
        return False
    limits = {c.criterion_id: c.max_points for c in rubric.criteria}
    earned = {
        i.criterion_id: limits[i.criterion_id] if parsed[i.item_id].choice == i.answer_key else 0
        for i in q.items
    }
    return earned == dict(case.expected_earned)


def evaluate(pack: Pack) -> EvaluationSummary:
    auto = passed = model = 0
    failures: list[str] = []
    for case in pack.evaluation_set:
        result = _run_key_scored_case(pack, case)
        if result is None:
            model += 1
            continue
        auto += 1
        if result:
            passed += 1
        else:
            failures.append(case.case_id)
    return EvaluationSummary(
        auto_cases=auto, auto_passed=passed, model_cases=model, failures=tuple(failures)
    )


def validate_package(raw: Mapping[str, Any]) -> ValidatedPackage:
    text = canonical_json(raw)
    digest = hashlib.sha256(text.encode()).hexdigest()
    cid, ver, title = _identity(raw)

    def result(errors: list[PackageIssue]) -> ValidatedPackage:
        return ValidatedPackage(
            report=ValidationReport(validator_version=VALIDATOR_VERSION, errors=tuple(errors)),
            course_id=cid,
            version=ver,
            title=title,
            canonical_json=text,
            content_hash=digest,
        )

    if len(text.encode()) > MAX_PACKAGE_BYTES:
        return result(
            [
                PackageIssue(
                    path="$",
                    code="too_large",
                    message=f"packages are limited to {MAX_PACKAGE_BYTES} bytes",
                )
            ]
        )
    try:
        pkg = CoursePackage.model_validate(raw)
    except ValidationError as exc:
        return result(_schema_issues(exc))

    pack, issues = build_pack(pkg)
    if not issues:  # indexes are reliable only without duplicates
        issues.extend(pack_issues(pack))
    issues.extend(_prompt_issues(pkg.system_prompt))
    evaluation = evaluate(pack) if not issues else EvaluationSummary()
    report = ValidationReport(
        validator_version=VALIDATOR_VERSION, errors=tuple(issues), evaluation=evaluation
    )
    return ValidatedPackage(
        report=report,
        course_id=cid,
        version=ver,
        title=title,
        canonical_json=text,
        content_hash=digest,
        package=pkg,
        pack=pack if report.valid else None,
    )


class PlatformPackageValidator:
    """Adapter for the domain `PackageValidator` port."""

    def validate(self, raw: Mapping[str, Any]) -> ValidatedPackage:
        return validate_package(raw)
