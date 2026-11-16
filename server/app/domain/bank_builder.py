"""Selection → course package version (Step 45.4, COURSE_PACKAGE.md §7).

A pure, deterministic function: the same selection, item versions, passages and base
package always produce the same package JSON. No model calls, no I/O.

- Each selection set becomes one choice-set question (≤10 multiple-choice items, scored by
  answer key). A set's shared passages become the question prompt.
- One rubric per set with one criterion per item; evaluation cases: every set answered all
  correct, then one-wrong cases while the 200-case limit allows, and one unreadable case.
- The course's manifest, tutor prompt and skills come from the base package (the latest
  package version of the course in the organization); questions, rubrics, starter tasks,
  practice sequence and evaluation set come from the selection. Materials are dropped,
  and abilities that need data a selection cannot provide (free-response grading, source
  analysis) are removed; `choice-scoring` is added.
- Every built question's `source.bankItems` records the bank item versions it came from;
  its review names the content reviewers who approved those versions.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.domain.types.bank import (
    BankItemVersion,
    BankPassage,
    ItemType,
    Selection,
    SelectionSet,
)

MAX_EVALUATION_CASES = 200
SCHEMA_VERSION = "course-package/v1"
# Abilities that need content a selection cannot produce yet.
UNBUILDABLE_ABILITIES = frozenset({"rubric-assessment", "source-analysis"})
NO_PASSAGE_PROMPT = (
    "Answer each question. Ask the tutor for a hint whenever you need one; hint use is recorded."
)


class BuildError(Exception):
    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = list(problems)


def slug(value: str) -> str:
    out = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    return out or "x"


def _short_hash(data: Any) -> str:
    raw = json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()[:10]


def _wrong(key: str) -> str:
    return "B" if key == "A" else "A"


def _answer(item: Mapping[str, Any], wrong_item: str) -> str:
    key = str(item["answerKey"])
    return _wrong(key) if item["itemId"] == wrong_item else key


def _set_items(
    st: SelectionSet, versions: Mapping[tuple[str, int], BankItemVersion]
) -> list[BankItemVersion]:
    return [versions[(r.item_id, r.version)] for r in st.items]


def _set_skills(st: SelectionSet, items: Sequence[BankItemVersion]) -> list[str]:
    skills: list[str] = []
    for v in items:
        skills.extend(v.content.skill_ids)
    skills.extend(st.skill_ids)
    return list(dict.fromkeys(skills))


def build_package(
    base: Mapping[str, Any],
    selection: Selection,
    versions: Mapping[tuple[str, int], BankItemVersion],
    passages: Mapping[str, BankPassage],
    package_version: str,
) -> dict[str, Any]:
    """The package JSON (camelCase, as uploaded). Raises BuildError with every problem."""
    problems: list[str] = []
    manifest = dict(base["manifest"])
    course = selection.course_id
    if manifest.get("courseId") != course:
        problems.append(f"the base package is for {manifest.get('courseId')}, not {course}")
    skill_ids = {s["skillId"] for s in base.get("skills", [])}
    task_types = list(manifest.get("supportedTaskTypes") or ["PRACTICE"])
    modes = list(manifest.get("supportedModes") or ["ADAPTIVE"])
    task_type = "PRACTICE" if "PRACTICE" in task_types else task_types[0]
    mode = "ADAPTIVE" if "ADAPTIVE" in modes else modes[0]
    publisher = (manifest.get("publisher") or {}).get("name") or "Unknown publisher"
    source_base = {
        "type": selection.source_type.value,
        "author": selection.source_author or publisher,
        "license": selection.source_license or manifest.get("license") or "Unspecified",
    }

    questions: list[dict[str, Any]] = []
    rubrics: list[dict[str, Any]] = []
    question_of: dict[str, str] = {}
    for st in selection.sets:
        items = _set_items(st, versions)
        label = f"set {st.set_id}"
        if any(v.content.item_type is not ItemType.MC for v in items):
            problems.append(f"{label}: only multiple-choice items can be built yet")
            continue
        skills = _set_skills(st, items)
        if not skills:
            problems.append(f"{label}: no skill — tag the items or give the set skillIds")
            continue
        unknown = [s for s in skills if s not in skill_ids]
        if unknown:
            problems.append(f"{label}: skills not in the course: {', '.join(unknown)}")
            continue
        qid = f"q_{course}_{slug(st.set_id)}"
        rubric_id = slug(f"{course}-{st.set_id}")
        content_version = "h" + _short_hash(
            [[r.item_id, r.version] for r in st.items] + [st.title, skills, st.difficulty]
        )
        approvers = sorted({v.review.reviewer_id for v in items if v.review is not None})
        decided = max((v.review.decided_at for v in items if v.review is not None), default=None)
        if not approvers or decided is None:  # selections only hold approved versions
            problems.append(f"{label}: an item version has no approval record")
            continue
        review = {
            "status": "reviewed",
            "reviewer": ", ".join(approvers),
            "reviewedAt": decided.date().isoformat(),
        }
        passage_ids = list(
            dict.fromkeys(v.content.passage_id for v in items if v.content.passage_id)
        )
        if passage_ids:
            parts = [
                f"{passages[p].title}\n\n{passages[p].text}" for p in passage_ids if p in passages
            ]
            prompt = "Read the passage, then answer each question.\n\n" + "\n\n---\n\n".join(parts)
        else:
            prompt = NO_PASSAGE_PROMPT
        choice_items, criteria = [], []
        for n, v in enumerate(items, start=1):
            c = v.content
            assert c.choices is not None and c.answer is not None  # approved mc items
            item_skills = [s for s in c.skill_ids if s in skill_ids] or skills
            choice_items.append(
                {
                    "itemId": str(n),
                    "prompt": c.stem,
                    "choices": [{"key": k, "text": c.choices[k]} for k in sorted(c.choices)],
                    "answerKey": c.answer,
                    "criterionId": f"item-{n}",
                }
            )
            criteria.append(
                {
                    "criterionId": f"item-{n}",
                    "description": f"Item {n}: selects the correct choice.",
                    "maxPoints": 1,
                    "evidenceRequirements": [f"Selects choice {c.answer} for item {n}"],
                    "skillIds": item_skills,
                }
            )
        questions.append(
            {
                "questionId": qid,
                "version": content_version,
                "courseId": course,
                "topic": st.title,
                "skillIds": skills,
                "difficulty": st.difficulty,
                "prompt": prompt,
                "expectedAnswer": ", ".join(
                    f"{i['itemId']}: {i['answerKey']}" for i in choice_items
                ),
                "rubricRef": {"rubricId": rubric_id, "version": content_version},
                "items": choice_items,
                "source": {
                    **source_base,
                    "bankItems": [{"itemId": r.item_id, "version": r.version} for r in st.items],
                },
                "review": review,
            }
        )
        rubrics.append(
            {
                "rubricId": rubric_id,
                "version": content_version,
                "courseId": course,
                "criteria": criteria,
                "source": source_base,
                "review": review,
            }
        )
        question_of[st.set_id] = qid
    if not questions and not problems:
        problems.append("the selection has no sets")
    if problems:
        raise BuildError(problems)

    evaluation: list[dict[str, Any]] = []
    for q in questions:
        evaluation.append(
            {
                "caseId": f"{slug(q['questionId'])}-all-correct",
                "questionId": q["questionId"],
                "answerText": "\n".join(f"{i['itemId']}: {i['answerKey']}" for i in q["items"]),
                "expectedStatus": "accepted",
                "expectedEarned": {i["criterionId"]: 1 for i in q["items"]},
            }
        )
    for q in questions:
        if len(evaluation) >= MAX_EVALUATION_CASES - 1:
            break
        first = q["items"][0]["itemId"]
        evaluation.append(
            {
                "caseId": f"{slug(q['questionId'])}-one-wrong",
                "questionId": q["questionId"],
                "answerText": "\n".join(f"{i['itemId']}: {_answer(i, first)}" for i in q["items"]),
                "expectedStatus": "accepted",
                "expectedEarned": {
                    i["criterionId"]: 0 if i["itemId"] == first else 1 for i in q["items"]
                },
            }
        )
    evaluation.append(
        {
            "caseId": f"{slug(questions[0]['questionId'])}-unreadable",
            "questionId": questions[0]["questionId"],
            "answerText": "I think the first one is A, not sure about the rest.",
            "expectedStatus": "insufficient_evidence",
            "expectedEarned": {},
        }
    )

    def tasks(set_ids: Sequence[str]) -> list[dict[str, Any]]:
        by_id = {st.set_id: st for st in selection.sets}
        return [
            {
                "questionId": question_of[sid],
                "taskType": task_type,
                "mode": mode,
                "title": by_id[sid].task_title,
                "durationMin": by_id[sid].duration_min,
            }
            for sid in set_ids
        ]

    abilities = [a for a in manifest.get("abilities", []) if a not in UNBUILDABLE_ABILITIES]
    if "choice-scoring" not in abilities:
        abilities.append("choice-scoring")
    manifest.update(version=package_version, abilities=abilities)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "manifest": manifest,
        "systemPrompt": base["systemPrompt"],
        "skills": base["skills"],
        "rubrics": rubrics,
        "questions": questions,
        "materials": [],
        "starterTasks": tasks(selection.starter_set_ids),
        "practiceSequence": tasks(selection.sequence_set_ids),
        "evaluationSet": evaluation,
    }
