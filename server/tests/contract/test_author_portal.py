"""Step 34.1 and 34.4: what the author portal reads.

- Preview: an author sees a version as a student would — no answer keys, expected
  answers, rubrics, system prompt or evaluation set. Another organization gets 404.
- Metrics: aggregates maintained exactly once per assessment by the course-metrics
  consumer, withheld below the minimum cohort, never carrying a student id.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.domain.types.actor import ActorContext
from app.domain.types.course_metrics import MIN_COHORT
from app.workers.consumers.course_metrics import CourseMetricsConsumer
from tests.support import Harness, build_harness

ALEX = "stu_alex"
AUTHOR, OTHER_AUTHOR, REVIEWER = "author_hsos", "author_sample", "reviewer_platform"
DSAT_PREVIEW = "/api/authoring/packages/dsat/versions/1.0.0/preview"
METRICS = "/api/authoring/courses/dsat/metrics"
SERVER_ONLY = ("answerKey", "expectedAnswer", "rubric", "systemPrompt", "evaluationSet")


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch) -> Harness:
    return build_harness(clean_env, course_metrics_enabled=True)


async def get(h: Harness, path: str, uid: str, status: int = 200) -> Any:
    r = await h.client.get(path, headers=h.auth(uid))
    assert r.status_code == status, r.text
    return r.json()


async def test_preview_is_the_student_view(h: Harness) -> None:
    preview = await get(h, DSAT_PREVIEW, AUTHOR)
    assert preview["courseId"] == "dsat" and preview["questions"]
    assert all(q["items"] for q in preview["questions"])
    text = json.dumps(preview)
    for field in SERVER_ONLY:
        assert field not in text
    assert [t["questionId"] for t in preview["starterTasks"]] == [
        "q_dsat_equiv_001", "q_dsat_nonlin_001",
    ]  # fmt: skip


async def test_preview_shows_source_documents_and_is_scoped(h: Harness) -> None:
    path = "/api/authoring/packages/apush/versions/1.0.0/preview"
    preview = await get(h, path, AUTHOR)
    dbq = next(q for q in preview["questions"] if q["questionId"] == "q_apush_dbq_001")
    assert [s["materialId"] for s in dbq["sources"]] == [
        "mat_apush_doc_a_federalist10", "mat_apush_doc_b_brutus1",
    ]  # fmt: skip
    await get(h, path, OTHER_AUTHOR, 404)  # another organization's package
    await get(h, path, ALEX, 403)  # students are not platform members
    review = await get(h, "/api/review/packages/apush/versions/1.0.0/preview", REVIEWER)
    assert review["courseId"] == "apush"


async def submit_dsat(h: Harness) -> None:
    r = await h.client.post(
        "/api/sessions", json={"taskId": "task_alex_dsat_01"}, headers=h.cmd(ALEX)
    )
    assert r.status_code == 201, r.text
    session = r.json()
    act = session["activity"]
    r = await h.client.post(
        f"/api/sessions/{session['sessionId']}/submissions",
        json={"questionId": act["questionId"], "questionVersion": act["questionVersion"],
              "answer": {"text": "1: A\n2: B\n3: B"}},
        headers=h.cmd(ALEX),
    )  # fmt: skip
    assert r.status_code == 202, r.text
    await h.settle()


async def test_metrics_count_each_assessment_once_and_hide_small_cohorts(h: Harness) -> None:
    await submit_dsat(h)
    raw = h.store.raw("courseMetrics/dsat")
    assert raw is not None
    assert (raw["students"], raw["assessments"], raw["byStatus"]) == (1, 1, {"accepted": 1})
    assert ALEX not in json.dumps(raw, default=str)  # no student id in the aggregate

    # Replaying the whole event log from the start changes nothing (receipts).
    h.store.put(
        f"students/{ALEX}/consumerState/course-metrics",
        {"consumer": "course-metrics", "processedSequence": 0, "updatedAt": h.clock.now()},
    )
    actor = ActorContext.for_service("event-consumers", ALEX)
    assert await h.services.consumers.drain(actor, CourseMetricsConsumer())
    assert h.store.raw("courseMetrics/dsat")["assessments"] == 1

    view = await get(h, METRICS, AUTHOR)
    assert view == {"courseId": "dsat", "suppressed": True, "minimumCohort": MIN_COHORT,
                    "students": None, "assessments": None, "byStatus": None,
                    "criteria": None, "updatedAt": None}  # fmt: skip


async def test_metrics_above_the_cohort_are_aggregates_only(h: Harness) -> None:
    h.put_doc(
        "courseMetrics/dsat",
        {"courseId": "dsat", "students": MIN_COHORT, "assessments": 8,
         "byStatus": {"accepted": 7, "insufficient_evidence": 1},
         "criteria": {"dsat-equiv-001:item-1": {"earned": 5, "possible": 7, "count": 7}},
         "updatedAt": h.clock.now()},
    )  # fmt: skip
    view = await get(h, METRICS, AUTHOR)
    assert view["suppressed"] is False and view["students"] == MIN_COHORT
    assert view["criteria"] == [
        {"rubricId": "dsat-equiv-001", "criterionId": "item-1", "count": 7,
         "averageEarned": 0.71, "maxPoints": 1.0},
    ]  # fmt: skip
    await get(h, METRICS, OTHER_AUTHOR, 404)
    await get(h, METRICS, ALEX, 403)
    await get(h, "/api/authoring/courses/calc_bc/metrics", AUTHOR, 404)  # bundled course
