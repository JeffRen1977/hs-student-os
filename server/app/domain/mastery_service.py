"""Mastery projection from accepted assessments (Step 18.2)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.catalog import CourseCatalog
from app.domain.ports.repositories import Tx, UnitOfWork
from app.domain.types.actor import ActorContext, Permission
from app.domain.types.assessment import Assessment
from app.domain.types.common import PageRequest, PaginatedResponse
from app.domain.types.mastery import (
    MasteryContribution,
    MasteryState,
    empty_mastery,
    evidence_application_id,
    project,
)


def course_of(skill_id: str) -> str:
    return skill_id.split(".", 1)[0]


def contributions_of(assessment: Assessment) -> dict[str, tuple[str, MasteryContribution]]:
    """Evidence application id → (skill, contribution). Empty unless the assessment is
    accepted: insufficient_evidence never touches mastery."""
    if not assessment.updates_mastery or assessment.created_at is None:
        return {}
    return {
        evidence_application_id(assessment.assessment_id, e.skill_id): (
            e.skill_id,
            MasteryContribution(
                assessment_id=assessment.assessment_id,
                question_id=assessment.question_id or "",
                observation=e.observation,
                recorded_at=assessment.created_at,
            ),
        )
        for e in assessment.skill_evidence
    }


def rebuild(assessments: Iterable[Assessment], *, now: datetime) -> dict[str, MasteryState]:
    """Recompute every skill's projection from scratch, honoring supersedes links."""
    items = list(assessments)
    superseded = {a.supersedes_assessment_id for a in items if a.supersedes_assessment_id}
    per_skill: dict[str, dict[str, MasteryContribution]] = {}
    for a in items:
        if a.assessment_id in superseded:
            continue
        for app_id, (skill, contribution) in contributions_of(a).items():
            per_skill.setdefault(skill, {})[app_id] = contribution
    return {
        skill: project(skill, course_of(skill), contributions, now=now)
        for skill, contributions in per_skill.items()
    }


async def apply_assessment(
    tx: Tx,
    actor: ActorContext,
    assessment: Assessment,
    *,
    superseded: Assessment | None,
    now: datetime,
) -> list[str]:
    """Apply one assessment's evidence (and withdraw the one it supersedes). Idempotent:
    evidence is keyed by application id, so re-applying changes nothing. Returns the skill
    ids whose projection changed."""
    added = contributions_of(assessment)
    removed = set(contributions_of(superseded)) if superseded else set()
    removed_skills = (
        {s for _, (s, _) in contributions_of(superseded).items()} if superseded else set()
    )
    skills = sorted({s for s, _ in added.values()} | removed_skills)
    changed: list[str] = []
    for skill in skills:
        current = await tx.mastery.get(actor, skill) or empty_mastery(skill, course_of(skill))
        contributions = {k: v for k, v in current.contributions.items() if k not in removed}
        for app_id, (s, contribution) in added.items():
            if s == skill:
                contributions[app_id] = contribution
        if contributions == dict(current.contributions):
            continue
        tx.mastery.save(actor, project(skill, course_of(skill), contributions, now=now))
        changed.append(skill)
    return changed


@dataclass(frozen=True, slots=True, kw_only=True)
class MasteryView:
    states: Sequence[MasteryState]
    next_cursor: str | None


class MasteryService:
    def __init__(
        self, uow: UnitOfWork, catalog: CourseCatalog, skills: Mapping[str, Sequence[str]]
    ):
        """`skills`: courseId → the course's skill ids (from the pack's skills.json)."""
        self._uow = uow
        self._catalog = catalog
        self._skills = skills

    async def list_for_course(
        self, actor: ActorContext, course_id: str, page: PageRequest
    ) -> PaginatedResponse[MasteryState]:
        """Every skill of the course, including ones with no evidence (insufficient)."""
        actor.require(Permission.LEARNING_READ)
        if self._catalog.get(course_id) is None:
            raise DomainError(ErrorCode.NOT_FOUND, "Course not found.")
        skill_ids = sorted(self._skills.get(course_id, ()))
        start = 0
        if page.cursor is not None:
            if page.cursor not in skill_ids:
                raise DomainError(ErrorCode.VALIDATION_FAILED, "invalid cursor")
            start = skill_ids.index(page.cursor) + 1
        window = skill_ids[start : start + page.limit]
        more = start + page.limit < len(skill_ids)

        async def read(tx: Tx) -> PaginatedResponse[MasteryState]:
            states = [await tx.mastery.get(actor, s) or empty_mastery(s, course_id) for s in window]
            return PaginatedResponse(items=states, next_cursor=window[-1] if more else None)

        return await self._uow.transaction(read)
