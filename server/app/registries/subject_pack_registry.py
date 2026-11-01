"""SubjectPack registry: validated, versioned pack content for the skill runtime (Step 17.1).

Only `active` packs are runnable. With `require_reviewed=True` (enforced in production),
content still in `draft` review is withheld: an unreviewed question cannot start a session
and an unreviewed material cannot be retrieved.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from app.domain.ports.content import (
    AnswerCheck,
    CriterionContent,
    MaterialContent,
    ModelTier,
    PackContent,
    QuestionContent,
    RubricContent,
)
from app.registries.content import ContentRegistry, Pack
from app.schemas.content import Material, Question, Rubric


def _rubric(r: Rubric) -> RubricContent:
    return RubricContent(
        rubric_id=r.rubric_id,
        version=r.version,
        course_id=r.course_id,
        criteria=tuple(
            CriterionContent(
                criterion_id=c.criterion_id,
                description=c.description,
                max_points=c.max_points,
                evidence_requirements=tuple(c.evidence_requirements),
                skill_ids=tuple(c.skill_ids),
            )
            for c in r.criteria
        ),
    )


def _question(q: Question) -> QuestionContent:
    check = q.answer_check
    return QuestionContent(
        question_id=q.question_id,
        version=q.version,
        course_id=q.course_id,
        topic=q.topic,
        prompt=q.prompt,
        skill_ids=tuple(q.skill_ids),
        rubric_id=q.rubric_ref.rubric_id,
        rubric_version=q.rubric_ref.version,
        answer_check=(
            AnswerCheck(
                criterion_id=check.criterion_id,
                expression=check.expression,
                variables=tuple(check.variables),
            )
            if check
            else None
        ),
        reviewed=q.review.status == "reviewed",
    )


def _material(m: Material) -> MaterialContent:
    return MaterialContent(
        material_id=m.material_id,
        course_id=m.course_id,
        skill_ids=tuple(m.skill_ids),
        title=m.title,
        text=m.text,
        source_ref=f"{m.material_id}@{m.version} ({m.source.author}; {m.source.license})",
        content_hash=hashlib.sha256(m.text.encode()).hexdigest()[:16],
    )


class ContentSubjectPackRegistry:
    def __init__(self, content: ContentRegistry, *, require_reviewed: bool = False) -> None:
        self._content = content
        self._require_reviewed = require_reviewed

    def _active(self, course_id: str) -> Pack | None:
        pack = self._content.pack(course_id)
        return pack if pack is not None and pack.is_active else None

    def pack(self, course_id: str) -> PackContent | None:
        pack = self._active(course_id)
        if pack is None:
            return None
        m = pack.manifest
        assert m.workflow_version and m.model_tier and pack.system_prompt is not None
        reviewed = all(q.review.status == "reviewed" for q in pack.questions.values()) and all(
            r.review.status == "reviewed" for r in pack.rubrics.values()
        )
        return PackContent(
            course_id=m.course_id,
            pack_version=m.version,
            workflow_version=m.workflow_version,
            system_prompt=pack.system_prompt,
            model_tier=ModelTier(m.model_tier),
            context_budget_tokens=m.context_budget_tokens,
            tools=tuple(m.tools),
            skill_names={s.skill_id: s.name for s in pack.skills.skills} if pack.skills else {},
            reviewed=reviewed,
        )

    def question(self, course_id: str, question_id: str) -> QuestionContent | None:
        pack = self._active(course_id)
        q = pack.questions.get(question_id) if pack else None
        if q is None:
            return None
        if self._require_reviewed and q.review.status != "reviewed":
            return None
        return _question(q)

    def rubric(self, course_id: str, rubric_id: str, version: str) -> RubricContent | None:
        pack = self._active(course_id)
        r = pack.rubrics.get((rubric_id, version)) if pack else None
        if r is None:
            return None
        if self._require_reviewed and r.review.status != "reviewed":
            return None
        return _rubric(r)

    def materials(self, course_id: str) -> Sequence[MaterialContent]:
        pack = self._active(course_id)
        if pack is None:
            return ()
        return tuple(
            _material(m)
            for m in pack.materials.values()
            if not self._require_reviewed or m.review.status == "reviewed"
        )
