from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.domain.types.course import CourseDefinition, QuestionInfo


class CourseCatalog(Protocol):
    """Read-only view of the versioned SubjectPack registry."""

    def get(self, course_id: str) -> CourseDefinition | None: ...

    def list(self) -> Sequence[CourseDefinition]: ...

    def question(self, course_id: str, question_id: str) -> QuestionInfo | None: ...
