"""Step 18.2: mastery is a pure, rebuildable projection of accepted assessments."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.adapters.firestore.memory_store import MemoryDocumentStore
from app.adapters.firestore.unit_of_work import DocumentUnitOfWork
from app.domain.mastery_service import apply_assessment, rebuild
from app.domain.ports.repositories import Tx
from app.domain.types.actor import ActorContext
from app.domain.types.assessment import (
    Assessment,
    AssessmentStatus,
    EvidenceObservation,
    HintUsage,
    Provenance,
    SkillEvidence,
    Uncertainty,
    UncertaintyLevel,
)
from app.domain.types.mastery import MasteryContribution, MasteryState, project
from app.domain.types.student import MasteryLevel

T0 = datetime(2026, 11, 2, tzinfo=UTC)
SKILL = "calc_bc.chain-rule"
ACTOR = ActorContext.for_service("run-worker", "stu_alex")


def assessment(
    aid: str,
    observation: EvidenceObservation | None,
    *,
    minutes: int = 0,
    question: str = "q1",
    supersedes: str | None = None,
) -> Assessment:
    accepted = observation is not None
    return Assessment(
        assessment_id=aid,
        student_id="stu_alex",
        submission_id=f"sub_{aid}",
        session_id="sess",
        run_id=f"run_{aid}",
        status=AssessmentStatus.ACCEPTED if accepted else AssessmentStatus.INSUFFICIENT_EVIDENCE,
        question_id=question,
        question_version="1",
        rubric_version="1",
        rubric_results=(),
        hint_usage=HintUsage(server_hint_count=0),
        skill_evidence=(SkillEvidence(skill_id=SKILL, observation=observation),)
        if observation
        else (),
        uncertainty=Uncertainty(level=UncertaintyLevel.LIMITED),
        provenance=Provenance(model_version="m", workflow_version="w"),
        supersedes_assessment_id=supersedes,
        created_at=T0 + timedelta(minutes=minutes),
    )


def contributions(*obs: EvidenceObservation) -> dict[str, MasteryContribution]:
    return {
        f"a{i}:{SKILL}": MasteryContribution(
            assessment_id=f"a{i}",
            question_id=f"q{i}",
            observation=o,
            recorded_at=T0 + timedelta(minutes=i),
        )
        for i, o in enumerate(obs)
    }


CI = EvidenceObservation.CORRECT_INDEPENDENT
CH = EvidenceObservation.CORRECT_WITH_HINT
INC = EvidenceObservation.INCORRECT


def test_levels_follow_the_documented_rules() -> None:
    def level(*obs: EvidenceObservation) -> MasteryLevel:
        return project(SKILL, "calc_bc", contributions(*obs), now=T0).level

    assert level() is MasteryLevel.INSUFFICIENT_EVIDENCE
    assert level(CH, CH, CH) is MasteryLevel.EMERGING  # assisted only: never beyond emerging
    assert level(CI) is MasteryLevel.DEVELOPING
    assert level(CI, CI, CI) is MasteryLevel.PROFICIENT
    assert level(CI, CI, CI, INC) is MasteryLevel.DEVELOPING  # a recent error holds it back
    state = project(SKILL, "calc_bc", contributions(CI, CH), now=T0)
    assert (state.independent_evidence_count, state.evidence_count, state.coverage) == (1, 2, 2)


async def _apply(
    store: MemoryDocumentStore, a: Assessment, sup: Assessment | None = None
) -> list[str]:
    async def body(tx: Tx) -> list[str]:
        return await apply_assessment(tx, ACTOR, a, superseded=sup, now=T0)

    return await DocumentUnitOfWork(store).transaction(body)


async def _state(store: MemoryDocumentStore) -> MasteryState | None:
    async def body(tx: Tx) -> MasteryState | None:
        return await tx.mastery.get(ACTOR, SKILL)

    return await DocumentUnitOfWork(store).transaction(body)


async def test_same_evidence_applies_once() -> None:
    store = MemoryDocumentStore()
    a1 = assessment("a1", CI)
    assert await _apply(store, a1) == [SKILL]
    assert await _apply(store, a1) == []  # replay: no change
    state = await _state(store)
    assert state is not None and state.evidence_count == 1


async def test_insufficient_evidence_never_touches_mastery() -> None:
    store = MemoryDocumentStore()
    assert await _apply(store, assessment("a1", None)) == []
    assert await _state(store) is None


async def test_regrade_replaces_instead_of_stacking() -> None:
    store = MemoryDocumentStore()
    original = assessment("a1", INC)
    await _apply(store, original)
    regrade = assessment("a2", CI, minutes=5, supersedes="a1")
    await _apply(store, regrade, original)
    state = await _state(store)
    assert state is not None
    assert (state.evidence_count, state.independent_evidence_count) == (1, 1)
    assert set(state.contributions) == {f"a2:{SKILL}"}

    # Regrading to insufficient_evidence withdraws the contribution entirely.
    third = assessment("a3", None, minutes=9, supersedes="a2")
    await _apply(store, third, regrade)
    state = await _state(store)
    assert state is not None and state.evidence_count == 0
    assert state.level is MasteryLevel.INSUFFICIENT_EVIDENCE


async def test_rebuild_matches_incremental_projection() -> None:
    store = MemoryDocumentStore()
    history = [
        assessment("a1", INC, minutes=1, question="q1"),
        assessment("a2", CI, minutes=2, question="q2"),
        assessment("a3", CH, minutes=3, question="q2"),
        assessment("a4", None, minutes=4),
    ]
    for a in history:
        await _apply(store, a)
    regrade = assessment("a5", CI, minutes=6, question="q1", supersedes="a1")
    await _apply(store, regrade, history[0])
    incremental = await _state(store)
    rebuilt = rebuild([*history, regrade], now=T0)[SKILL]
    assert incremental is not None
    assert (rebuilt.level, rebuilt.evidence_count, rebuilt.independent_evidence_count,
            rebuilt.coverage, set(rebuilt.contributions)) == (
        incremental.level, incremental.evidence_count, incremental.independent_evidence_count,
        incremental.coverage, set(incremental.contributions),
    )  # fmt: skip


def test_independent_evidence_counts_each_question_once_from_its_first_attempt() -> None:
    """Re-answering the same question in new sessions is not a new independent measurement:
    three correct answers to one question never make a skill proficient."""

    def state_of(*items: tuple[str, EvidenceObservation]) -> MasteryState:
        return project(
            SKILL,
            "calc_bc",
            {
                f"a{i}:{SKILL}": MasteryContribution(
                    assessment_id=f"a{i}",
                    question_id=q,
                    observation=o,
                    recorded_at=T0 + timedelta(minutes=i),
                )
                for i, (q, o) in enumerate(items)
            },
            now=T0,
        )

    repeated = state_of(("q1", CI), ("q1", CI), ("q1", CI))
    assert (repeated.independent_evidence_count, repeated.evidence_count) == (1, 3)
    assert repeated.level is MasteryLevel.DEVELOPING and repeated.coverage == 1

    # Wrong the first time, right in a later session: a correction, not independent.
    corrected = state_of(("q1", INC), ("q1", CI))
    assert corrected.independent_evidence_count == 0
    assert corrected.level is MasteryLevel.EMERGING

    spread = state_of(("q1", CI), ("q2", CI), ("q3", CI))
    assert spread.independent_evidence_count == 3 and spread.level is MasteryLevel.PROFICIENT
