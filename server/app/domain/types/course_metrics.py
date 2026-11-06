"""Privacy-safe aggregate course metrics for authors (Step 34.4).

Authors never see individual student data (CLAUDE.md "Course packages and authoring").
What they get is a per-course aggregate maintained by a consumer of `assessment.completed`:
counts and per-criterion point totals, with no student ids, answers, feedback or dates
finer than the last update. Below `MIN_COHORT` distinct students the aggregate is
suppressed entirely, so a small cohort cannot be used to infer one student's results.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

MIN_COHORT = 5


@dataclass(frozen=True, slots=True, kw_only=True)
class CriterionTotals:
    earned: int = 0
    possible: int = 0
    count: int = 0  # accepted assessments that scored this criterion


@dataclass(frozen=True, slots=True, kw_only=True)
class CourseMetrics:
    course_id: str
    students: int = 0  # distinct students with at least one assessment in the course
    assessments: int = 0
    by_status: Mapping[str, int] = field(default_factory=dict)
    # "{rubricId}:{criterionId}" → totals over accepted assessments only
    criteria: Mapping[str, CriterionTotals] = field(default_factory=dict)
    updated_at: datetime | None = None

    @property
    def suppressed(self) -> bool:
        return self.students < MIN_COHORT
