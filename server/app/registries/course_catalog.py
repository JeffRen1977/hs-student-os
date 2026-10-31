"""Adapts the SubjectPack content registry to the domain `CourseCatalog` port."""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.types.course import AgentConfig, CourseDefinition, QuestionInfo
from app.registries.content import ContentRegistry, Pack


def _definition(pack: Pack) -> CourseDefinition:
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
    )


class RegistryCourseCatalog:
    def __init__(self, registry: ContentRegistry) -> None:
        self._registry = registry
        self._courses = {cid: _definition(p) for cid, p in sorted(registry.packs.items())}

    def get(self, course_id: str) -> CourseDefinition | None:
        return self._courses.get(course_id)

    def list(self) -> Sequence[CourseDefinition]:
        return list(self._courses.values())

    def question(self, course_id: str, question_id: str) -> QuestionInfo | None:
        pack = self._registry.pack(course_id)
        question = pack.questions.get(question_id) if pack else None
        if question is None:
            return None
        return QuestionInfo(
            question_id=question.question_id, version=question.version, course_id=course_id
        )
