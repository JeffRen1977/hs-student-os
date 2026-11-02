"""Adapts the content registry to the domain `CourseCatalog` port.

Reads the registry on every call, so authored packages activated or retired at runtime
(`PackageContentSync`) are visible immediately. Retired courses are not listed in the
catalog, but `get` still returns them so past work stays readable and new work is refused
with a clear reason.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.types.course import (
    AgentConfig,
    CourseDefinition,
    QuestionInfo,
    StarterTaskSpec,
)
from app.registries.content import ContentRegistry, Pack


def course_definition(pack: Pack) -> CourseDefinition:
    m = pack.manifest
    return CourseDefinition(
        course_id=m.course_id,
        name=m.name,
        description=m.description,
        category=m.category,
        availability=m.availability,
        pack_version=m.version,
        workflow_version=m.workflow_version,
        agent=AgentConfig(
            agent_type=m.agent_type,
            modes=tuple(m.supported_modes),
            supported_task_types=tuple(m.supported_task_types),
            description=m.description,
        ),
        skills=tuple(m.skills),
        starter_tasks=tuple(
            StarterTaskSpec(
                question_id=s.question_id,
                task_type=s.task_type,
                mode=s.mode,
                title=s.title,
                duration_min=s.duration_min,
            )
            for s in pack.starter_tasks
        ),
        skill_names={s.skill_id: s.name for s in pack.skills.skills} if pack.skills else {},
    )


class RegistryCourseCatalog:
    def __init__(self, registry: ContentRegistry) -> None:
        self._registry = registry

    def get(self, course_id: str) -> CourseDefinition | None:
        pack = self._registry.pack(course_id)
        return course_definition(pack) if pack is not None else None

    def list(self) -> Sequence[CourseDefinition]:
        return [
            course_definition(p)
            for _, p in sorted(self._registry.packs.items())
            if not p.is_retired
        ]

    def question(self, course_id: str, question_id: str) -> QuestionInfo | None:
        pack = self._registry.pack(course_id)
        question = pack.questions.get(question_id) if pack else None
        if question is None:
            return None
        return QuestionInfo(
            question_id=question.question_id, version=question.version, course_id=course_id
        )
