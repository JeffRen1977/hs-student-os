"""The web demo fixtures (`web/fixtures/demo.json`) must match the API contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.schemas.course import CatalogResponse
from app.schemas.event import EventPage
from app.schemas.run import Run
from app.schemas.session import SessionList
from app.schemas.student import Entitlements, TwinSummary
from app.schemas.task import TaskList

DEMO_PATH = Path(__file__).resolve().parents[3] / "web" / "fixtures" / "demo.json"


@pytest.fixture(scope="module")
def demo() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(DEMO_PATH.read_text(encoding="utf-8"))
    return data


def test_demo_documents_validate(demo: dict[str, Any]) -> None:
    twin = TwinSummary.model_validate(demo["twin"])
    Entitlements.model_validate(demo["entitlements"])
    catalog = CatalogResponse.model_validate(demo["catalog"])
    tasks = TaskList.model_validate(demo["tasks"])
    sessions = SessionList.model_validate(demo["sessions"])
    runs = [Run.model_validate(r) for r in demo["runs"]]
    events = EventPage.model_validate(demo["events"])

    task_ids = {t.task_id for t in tasks.tasks}
    session_ids = {s.session_id for s in sessions.sessions}
    run_ids = {r.run_id for r in runs}
    assert all(s.task_id in task_ids for s in sessions.sessions)
    assert all(r.session_id in session_ids for r in runs)
    assert all(s.active_run_id in run_ids for s in sessions.sessions if s.active_run_id)
    assert all(t.student_id == twin.student_id for t in tasks.tasks)
    assert all(e.student_id == twin.student_id for e in events.events)
    assert [e.sequence for e in events.events] == sorted(e.sequence for e in events.events)
    assert events.events[-1].sequence == twin.latest_event_sequence

    # Only active + entitled courses can be enrolled.
    for course in catalog.courses:
        if course.enrolled:
            assert course.availability.value == "active" and course.entitled


def test_demo_predictions_unavailable(demo: dict[str, Any]) -> None:
    twin = TwinSummary.model_validate(demo["twin"])
    assert {p.status.value for p in twin.prediction_summary.values()} == {"unavailable"}
