from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.errors import DomainError, ErrorCode
from app.domain.types.actor import ActorContext, ActorRole, Permission
from app.domain.types.assessment import (
    Assessment,
    AssessmentStatus,
    EvidenceObservation,
    HintUsage,
    Provenance,
    RubricResult,
    SkillEvidence,
    Uncertainty,
    UncertaintyLevel,
)
from app.domain.types.common import PageRequest
from app.domain.types.event import DomainEvent, EventType
from app.domain.types.run import RUN_TRANSITIONS, Run, RunKind, RunStatus
from app.domain.types.session import (
    SESSION_TRANSITIONS,
    CompletionBlocker,
    CompletionEligibility,
    SessionStatus,
)
from app.domain.types.task import TASK_TRANSITIONS, TaskStatus
from app.domain.types.transitions import ensure_transition

# ---- State machines (CLAUDE.md §2.5) ---------------------------------------------------


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.PLANNED, TaskStatus.IN_PROGRESS),
        (TaskStatus.IN_PROGRESS, TaskStatus.COMPLETED),
        (TaskStatus.PLANNED, TaskStatus.SKIPPED),
    ],
)
def test_valid_task_transitions(current: TaskStatus, target: TaskStatus) -> None:
    ensure_transition(TASK_TRANSITIONS, current, target, entity="Task")


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.PLANNED, TaskStatus.COMPLETED),
        (TaskStatus.IN_PROGRESS, TaskStatus.SKIPPED),
        (TaskStatus.COMPLETED, TaskStatus.PLANNED),
        (TaskStatus.SKIPPED, TaskStatus.IN_PROGRESS),
    ],
)
def test_invalid_task_transitions(current: TaskStatus, target: TaskStatus) -> None:
    with pytest.raises(DomainError) as info:
        ensure_transition(TASK_TRANSITIONS, current, target, entity="Task")
    assert info.value.code is ErrorCode.INVALID_STATE_TRANSITION


def test_session_terminal_states_are_final() -> None:
    for terminal in (SessionStatus.COMPLETED, SessionStatus.ABANDONED):
        assert SESSION_TRANSITIONS[terminal] == frozenset()
    with pytest.raises(DomainError):
        ensure_transition(
            SESSION_TRANSITIONS, SessionStatus.COMPLETED, SessionStatus.ABANDONED, entity="S"
        )


def test_run_transitions() -> None:
    ensure_transition(RUN_TRANSITIONS, RunStatus.RUNNING, RunStatus.WAITING_INPUT, entity="R")
    ensure_transition(RUN_TRANSITIONS, RunStatus.WAITING_INPUT, RunStatus.QUEUED, entity="R")
    for terminal in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
        assert RUN_TRANSITIONS[terminal] == frozenset()
    with pytest.raises(DomainError):
        ensure_transition(RUN_TRANSITIONS, RunStatus.QUEUED, RunStatus.SUCCEEDED, entity="R")


# ---- ActorContext -----------------------------------------------------------------------


def test_student_actor_is_bound_to_own_student() -> None:
    actor = ActorContext.for_student("stu_alex")
    assert actor.can(Permission.LEARNING_COMMAND)
    assert not actor.can(Permission.ENTITLEMENTS_WRITE)
    with pytest.raises(ValueError, match="own student_id"):
        ActorContext(actor_id="stu_alex", student_id="stu_beth", role=ActorRole.STUDENT)


def test_service_actor_may_act_for_a_student() -> None:
    actor = ActorContext(
        actor_id="svc_worker",
        student_id="stu_beth",
        role=ActorRole.SERVICE,
        permissions=frozenset({Permission.RUN_EXECUTE}),
    )
    assert actor.student_id == "stu_beth"


# ---- Entity invariants ------------------------------------------------------------------


def test_only_planning_runs_may_omit_session() -> None:
    Run(
        run_id="r1", student_id="s", session_id=None, status=RunStatus.QUEUED, kind=RunKind.PLANNING
    )
    with pytest.raises(ValueError):
        Run(
            run_id="r2",
            student_id="s",
            session_id=None,
            status=RunStatus.QUEUED,
            kind=RunKind.ASSESS_SUBMISSION,
        )


def test_completion_eligibility_requires_reason_when_ineligible() -> None:
    CompletionEligibility(eligible=False, reason=CompletionBlocker.ACCEPTED_ASSESSMENT_REQUIRED)
    with pytest.raises(ValueError):
        CompletionEligibility(eligible=False)
    with pytest.raises(ValueError):
        CompletionEligibility(eligible=True, reason=CompletionBlocker.RUN_IN_PROGRESS)


def _assessment(**overrides: object) -> Assessment:
    fields: dict[str, object] = {
        "assessment_id": "a1",
        "student_id": "stu_alex",
        "submission_id": "sub1",
        "session_id": "sess1",
        "run_id": "run1",
        "status": AssessmentStatus.ACCEPTED,
        "question_version": "1",
        "rubric_version": "1",
        "rubric_results": [RubricResult(criterion_id="c", earned=1, possible=1)],
        "hint_usage": HintUsage(server_hint_count=0),
        "skill_evidence": [
            SkillEvidence(
                skill_id="calc_bc.chain-rule", observation=EvidenceObservation.CORRECT_INDEPENDENT
            )
        ],
        "uncertainty": Uncertainty(level=UncertaintyLevel.LOW),
        "provenance": Provenance(model_version="m", workflow_version="w"),
    }
    fields.update(overrides)
    return Assessment(**fields)  # type: ignore[arg-type]


def test_accepted_assessment_updates_mastery() -> None:
    assert _assessment().updates_mastery


def test_insufficient_evidence_never_carries_skill_evidence() -> None:
    with pytest.raises(ValueError, match="insufficient_evidence"):
        _assessment(status=AssessmentStatus.INSUFFICIENT_EVIDENCE)
    a = _assessment(status=AssessmentStatus.INSUFFICIENT_EVIDENCE, skill_evidence=[])
    assert not a.updates_mastery


def test_hint_assisted_work_is_not_independent() -> None:
    with pytest.raises(ValueError, match="hint-assisted"):
        _assessment(hint_usage=HintUsage(server_hint_count=1))


def test_rubric_result_bounds() -> None:
    with pytest.raises(ValueError):
        RubricResult(criterion_id="c", earned=2, possible=1)


def test_event_sequences_start_at_one() -> None:
    with pytest.raises(ValueError):
        DomainEvent(
            event_id="e",
            sequence=0,
            schema_version=1,
            student_id="s",
            type=EventType.PLAN_UPDATED,
            occurred_at=datetime.now(UTC),
            causation_id=None,
        )


def test_page_request_limits() -> None:
    assert PageRequest().limit == 50
    with pytest.raises(ValueError):
        PageRequest(limit=101)
