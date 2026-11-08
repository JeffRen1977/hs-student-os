"""Step 44: which ability handles a Run.

The first half pins the dispatch that existed before the ability registry, on three courses,
so the move onto the registry is a refactor with no change in behavior. A recording gateway
stops at the model call and reports which ability made it; no grading quality is measured.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.adapters.firestore.session_repository import session_from_doc, session_to_doc
from app.adapters.tools.math_verify import MathVerifyTool
from app.domain import skill_executor
from app.domain.ability_registry import AbilityRegistry, AbilityRegistryError
from app.domain.ports.content import MaterialContent, ModelTier
from app.domain.ports.execution import ExecutionFailure, ExecutionOutput, ExecutionRequest
from app.domain.ports.llm import LlmRequest, LlmResult
from app.domain.skill_executor import SkillExecutor
from app.domain.skills.ability import (
    AbilityContext,
    AbilityDataRule,
    AbilityDefinition,
    AbilityEvidence,
    QuestionShape,
)
from app.domain.skills.catalog import PLATFORM_ABILITIES, PLATFORM_ABILITY_REGISTRY
from app.domain.types.message import Message, MessageRole
from app.domain.types.run import Run, RunKind, RunStatus
from app.domain.types.session import (
    ContextVersion,
    Session,
    SessionActivity,
    SessionStatus,
    completion_for,
)
from app.domain.types.submission import Submission, SubmissionAnswer
from app.registries.content import (
    DEFAULT_CONTENT_ROOT,
    AuthoredVersion,
    Pack,
    load_content,
    pack_issues,
)
from app.registries.course_catalog import RegistryCourseCatalog
from app.registries.package_validator import validate_package
from app.registries.subject_pack_registry import ContentSubjectPackRegistry
from app.registries.tool_registry import ToolRegistry
from tests.support import FakeClock, Harness, SequentialIds

NOW = datetime(2026, 11, 8, 18, tzinfo=UTC)
KEY_SCORED = "key-scored"  # the ability answered without any model call
HINT = "socratic-guidance"
RUBRIC = "rubric-assessment"
SOURCED = "source-analysis"
CHOICE = "choice-scoring"


def _content() -> Any:
    content = load_content()
    versions = []
    for name in ("dsat/package-2.0.1.json", "apush/package.json"):
        raw = json.loads((DEFAULT_CONTENT_ROOT / "authored" / name).read_text())
        pack = validate_package(raw).pack
        assert pack is not None
        versions.append(AuthoredVersion(pack=pack, current=True))
    content.install_authored(versions)
    return content


CONTENT = _content()
PACKS = ContentSubjectPackRegistry(CONTENT)
CATALOG = RegistryCourseCatalog(CONTENT)


class ReachedModel(Exception):
    pass


class RecordingGateway:
    def __init__(self) -> None:
        self.purposes: list[str] = []

    async def generate[T](self, request: LlmRequest, parse: Callable[[Any], T]) -> LlmResult[T]:
        self.purposes.append(request.purpose)
        raise ReachedModel


class Fallback:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, request: ExecutionRequest) -> ExecutionOutput:
        self.calls += 1
        return ExecutionOutput(agent_text="synthetic", model_version="fallback", synthetic=True)


def session_for(course_id: str, question_id: str, skills: Sequence[str] | None = None) -> Session:
    q = PACKS.question(course_id, question_id)
    pack = PACKS.pack(course_id)
    course = CATALOG.get(course_id)
    assert q is not None and pack is not None and course is not None
    return Session(
        session_id="sess_1",
        student_id="stu_alex",
        task_id="task_1",
        course_id=course_id,
        status=SessionStatus.OPEN,
        active_run_id="run_1",
        context_version=ContextVersion(pack=pack.pack_version, workflow=pack.workflow_version),
        completion=completion_for(SessionStatus.OPEN, "run_1", False),
        version=1,
        agent_skills=tuple(course.skills) if skills is None else tuple(skills),
        activity=SessionActivity(
            question_id=q.question_id,
            question_version=q.version,
            rubric_id=q.rubric_id,
            rubric_version=q.rubric_version,
        ),
    )


def request_for(session: Session, kind: RunKind, *, submit: bool = True) -> ExecutionRequest:
    assert session.activity is not None
    assess = kind is RunKind.ASSESS_SUBMISSION
    q = PACKS.question(session.course_id, session.activity.question_id)
    assert q is not None
    text = "\n".join(f"{i.item_id}: A" for i in q.items) if q.items else "My answer."
    submission = Submission(
        submission_id="sub_1",
        student_id=session.student_id,
        session_id=session.session_id,
        question_id=session.activity.question_id,
        question_version=session.activity.question_version,
        answer=SubmissionAnswer(text=text),
        supersedes_submission_id=None,
        run_id="run_1",
        created_at=NOW,
        server_hint_count=0,
    )
    course = CATALOG.get(session.course_id)
    assert course is not None
    return ExecutionRequest(
        run=Run(
            run_id="run_1",
            student_id=session.student_id,
            session_id=session.session_id,
            status=RunStatus.RUNNING,
            kind=kind,
            submission_id="sub_1" if assess else None,
            attempt_count=1,
        ),
        session=session,
        course=course,
        student_text=text,
        submission=submission if assess and submit else None,
        history=[
            Message(
                message_id="m1",
                student_id=session.student_id,
                session_id=session.session_id,
                role=MessageRole.STUDENT,
                text="How do I start?",
                created_at=NOW,
            )
        ],
        student_name="Alex",
        mode="GPA_SYNC",
    )


def executor(gateway: RecordingGateway | None, **kwargs: Any) -> SkillExecutor:
    registry = kwargs.pop("registry", PACKS)
    tools = ToolRegistry([MathVerifyTool()])
    return SkillExecutor(gateway, registry, tools, FakeClock(), SequentialIds(), **kwargs)


async def dispatched(request: ExecutionRequest, **kwargs: Any) -> str:
    gateway = RecordingGateway()
    try:
        output = await executor(gateway, **kwargs).execute(request)
    except ReachedModel:
        return gateway.purposes[0]
    assert gateway.purposes == [] and output.assessment is not None
    return KEY_SCORED


COURSE_QUESTIONS = [
    ("calc_bc", "q_calc_bc_001", RUBRIC, KEY_SCORED),
    ("apush", "q_apush_saq_001", RUBRIC, KEY_SCORED),
    ("apush", "q_apush_dbq_001", SOURCED, KEY_SCORED),
    ("apush", "q_apush_mc_001", KEY_SCORED, KEY_SCORED),
    ("dsat", "q_dsat_equiv_001", KEY_SCORED, KEY_SCORED),
]
ABILITY_FOR = {RUBRIC: RUBRIC, SOURCED: SOURCED, KEY_SCORED: CHOICE}


@pytest.mark.parametrize(("course", "question", "expected", "_unused"), COURSE_QUESTIONS)
async def test_assessment_goes_to_the_ability_for_the_question_shape(
    course: str, question: str, expected: str, _unused: str
) -> None:
    request = request_for(session_for(course, question), RunKind.ASSESS_SUBMISSION)
    assert await dispatched(request) == expected


@pytest.mark.parametrize(("course", "question", "_expected", "_unused"), COURSE_QUESTIONS)
async def test_every_question_shape_gets_socratic_hints(
    course: str, question: str, _expected: str, _unused: str
) -> None:
    request = request_for(session_for(course, question), RunKind.HINT)
    assert await dispatched(request) == HINT


@pytest.mark.parametrize(("course", "question", "expected", "_unused"), COURSE_QUESTIONS)
async def test_the_session_must_have_the_needed_ability_enabled(
    course: str, question: str, expected: str, _unused: str
) -> None:
    course_skills = CATALOG.get(course).skills  # type: ignore[union-attr]
    skills = [s for s in course_skills if s != ABILITY_FOR[expected]]
    request = request_for(session_for(course, question, skills), RunKind.ASSESS_SUBMISSION)
    with pytest.raises(ExecutionFailure) as err:
        await executor(RecordingGateway()).execute(request)
    assert err.value.code == "SKILL_NOT_ENABLED"


async def test_hints_need_the_socratic_ability_enabled() -> None:
    request = request_for(session_for("calc_bc", "q_calc_bc_001", [RUBRIC]), RunKind.HINT)
    with pytest.raises(ExecutionFailure) as err:
        await executor(RecordingGateway()).execute(request)
    assert err.value.code == "SKILL_NOT_ENABLED"


@pytest.mark.parametrize(
    ("course", "question", "kind", "uses_fallback"),
    [
        ("dsat", "q_dsat_equiv_001", RunKind.ASSESS_SUBMISSION, False),
        ("apush", "q_apush_mc_001", RunKind.ASSESS_SUBMISSION, False),
        ("calc_bc", "q_calc_bc_001", RunKind.ASSESS_SUBMISSION, True),
        ("apush", "q_apush_dbq_001", RunKind.ASSESS_SUBMISSION, True),
        ("dsat", "q_dsat_equiv_001", RunKind.HINT, True),
    ],
)
async def test_without_a_model_only_key_scoring_runs(
    course: str, question: str, kind: RunKind, uses_fallback: bool
) -> None:
    fallback = Fallback()
    output = await executor(None, fallback=fallback).execute(
        request_for(session_for(course, question), kind)
    )
    assert fallback.calls == (1 if uses_fallback else 0)
    assert output.synthetic is uses_fallback


async def test_an_assessment_needs_its_submission() -> None:
    request = request_for(
        session_for("apush", "q_apush_saq_001"), RunKind.ASSESS_SUBMISSION, submit=False
    )
    with pytest.raises(ExecutionFailure) as err:
        await executor(RecordingGateway()).execute(request)
    assert err.value.code == "SUBMISSION_NOT_FOUND"


async def test_a_run_kind_no_ability_handles_is_refused() -> None:
    request = request_for(session_for("calc_bc", "q_calc_bc_001"), RunKind.PLANNING)
    with pytest.raises(ExecutionFailure) as err:
        await executor(RecordingGateway()).execute(request)
    assert err.value.code == "UNSUPPORTED_RUN_KIND"


class NoMaterials(ContentSubjectPackRegistry):
    def materials(self, course_id: str, version: str | None = None) -> Sequence[MaterialContent]:
        return ()


async def test_sourced_grading_never_runs_with_missing_documents() -> None:
    request = request_for(session_for("apush", "q_apush_dbq_001"), RunKind.ASSESS_SUBMISSION)
    with pytest.raises(ExecutionFailure) as err:
        await executor(RecordingGateway(), registry=NoMaterials(CONTENT)).execute(request)
    assert err.value.code == "COURSE_CONTENT_UNAVAILABLE"


# ---- The registry: a new ability needs no executor or validator change --------------------

TEST_ABILITY = "test-key-reader"


async def _test_handler(ctx: AbilityContext) -> ExecutionOutput:
    return ExecutionOutput(
        agent_text=f"handled {ctx.request.session.course_id}",
        model_version="test",
        synthetic=True,
    )


def definition(ability_id: str = TEST_ABILITY, **changes: Any) -> AbilityDefinition:
    fields: dict[str, Any] = {
        "ability_id": ability_id,
        "version": "1",
        "run_kinds": frozenset({RunKind.ASSESS_SUBMISSION}),
        "question_shapes": frozenset({QuestionShape.CHOICE_SET}),
        "needs_model": False,
        "model_tier_floor": None,
        "evidence": AbilityEvidence.ANSWER_KEY,
        "handler": _test_handler,
        "data_rule": AbilityDataRule(
            shape=QuestionShape.CHOICE_SET,
            missing_ability=f"needs {ability_id}",
            missing_data=f"{ability_id} needs a choice set",
        ),
    }
    return AbilityDefinition(**(fields | changes))


# The new ability takes over choice sets; the rest of the platform list is unchanged.
WITH_TEST_ABILITY = AbilityRegistry(
    [*(d for d in PLATFORM_ABILITIES if d.ability_id != CHOICE), definition()]
)


def selecting_test_ability(pack: Pack) -> Pack:
    skills = [TEST_ABILITY if s == CHOICE else s for s in pack.manifest.skills]
    return dataclasses.replace(pack, manifest=pack.manifest.model_copy(update={"skills": skills}))


@pytest.mark.parametrize(
    ("course", "question"), [("dsat", "q_dsat_equiv_001"), ("apush", "q_apush_mc_001")]
)
async def test_a_registered_ability_runs_for_two_courses_without_code_changes(
    course: str, question: str
) -> None:
    skills = [TEST_ABILITY if s == CHOICE else s for s in CATALOG.get(course).skills]  # type: ignore[union-attr]
    request = request_for(session_for(course, question, skills), RunKind.ASSESS_SUBMISSION)
    output = await executor(RecordingGateway(), abilities=WITH_TEST_ABILITY).execute(request)
    assert output.agent_text == f"handled {course}"
    pack = selecting_test_ability(CONTENT.packs[course])
    assert pack_issues(pack, WITH_TEST_ABILITY) == []


def test_an_ability_outside_the_registry_is_rejected_at_validation() -> None:
    pack = selecting_test_ability(CONTENT.packs["dsat"])
    found = {i.code for i in pack_issues(pack)}
    assert "unknown_ability" in found and "ability_not_selected" in found


def test_a_registered_ability_gets_data_checks_in_both_directions() -> None:
    assert {i.code for i in pack_issues(CONTENT.packs["dsat"], WITH_TEST_ABILITY)} >= {
        "unknown_ability",  # choice-scoring is not in this registry
        "ability_not_selected",
    }
    pack = selecting_test_ability(CONTENT.packs["dsat"])
    no_choice = dataclasses.replace(
        pack, questions={k: q.model_copy(update={"items": None}) for k, q in pack.questions.items()}
    )
    assert "ability_without_data" in {i.code for i in pack_issues(no_choice, WITH_TEST_ABILITY)}


def test_a_pack_below_an_abilitys_model_floor_is_rejected() -> None:
    floor = definition(model_tier_floor=ModelTier.STRONG)
    registry = AbilityRegistry([*(d for d in PLATFORM_ABILITIES if d.ability_id != CHOICE), floor])
    pack = selecting_test_ability(CONTENT.packs["dsat"])
    assert "model_tier_below_floor" in {i.code for i in pack_issues(pack, registry)}
    assert pack.manifest.model_tier != ModelTier.STRONG.value


def test_duplicate_ability_ids_stop_startup() -> None:
    with pytest.raises(AbilityRegistryError, match="duplicate"):
        AbilityRegistry([definition(), definition()])


def test_two_abilities_on_one_route_stop_startup() -> None:
    with pytest.raises(AbilityRegistryError, match="both handle"):
        AbilityRegistry([definition(), definition("other", data_rule=None)])


def test_two_abilities_requiring_one_shape_stop_startup() -> None:
    other = definition("other", run_kinds=frozenset({RunKind.HINT}))
    with pytest.raises(AbilityRegistryError, match="both require"):
        AbilityRegistry([definition(), other])


def test_the_runtime_names_no_ability() -> None:
    source = (Path(skill_executor.__file__)).read_text()
    assert not any(d.ability_id in source for d in PLATFORM_ABILITIES)


def test_the_author_guide_lists_every_ability_with_its_version() -> None:
    guide = (Path(__file__).parents[3] / "doc/AUTHORING_GUIDE.md").read_text()
    for d in PLATFORM_ABILITIES:
        assert f"| `{d.ability_id}` | {d.version} |" in guide


# ---- Ability versions pinned on the Session ------------------------------------------------


def test_new_sessions_pin_the_selected_abilities_only() -> None:
    assert PLATFORM_ABILITY_REGISTRY.versions_for([HINT, "not-registered"]) == {HINT: "1"}


async def test_session_creation_pins_ability_versions(harness: Harness) -> None:
    response = await harness.client.post(
        "/api/sessions", json={"taskId": "task_alex_calc_01"}, headers=harness.cmd("stu_alex")
    )
    assert response.status_code == 201
    assert "abilityVersions" not in response.json()  # internal: never projected to the client
    stored = harness.store.raw(f"students/stu_alex/sessions/{response.json()['sessionId']}")
    assert stored["abilityVersions"] == {s: "1" for s in stored["agentSkills"]}
    assert stored["abilityVersions"]


async def test_an_open_session_refuses_a_changed_ability_version() -> None:
    session = session_for("dsat", "q_dsat_equiv_001")
    pinned = dataclasses.replace(session, ability_versions={CHOICE: "0"})
    with pytest.raises(ExecutionFailure) as err:
        await executor(RecordingGateway()).execute(request_for(pinned, RunKind.ASSESS_SUBMISSION))
    assert err.value.code == "CONTENT_VERSION_CHANGED"


async def test_a_session_pinned_to_the_current_version_runs() -> None:
    session = session_for("dsat", "q_dsat_equiv_001")
    pinned = dataclasses.replace(session, ability_versions={CHOICE: "1"})
    request = request_for(pinned, RunKind.ASSESS_SUBMISSION)
    assert await dispatched(request) == KEY_SCORED


def test_pinned_versions_survive_storage_and_older_documents_load() -> None:
    session = dataclasses.replace(
        session_for("dsat", "q_dsat_equiv_001"), ability_versions={CHOICE: "1"}
    )
    now = {"createdAt": NOW, "updatedAt": NOW}
    doc = {**session_to_doc(session), **now}
    assert session_from_doc(doc).ability_versions == {CHOICE: "1"}
    del doc["abilityVersions"]
    assert session_from_doc(doc).ability_versions == {}
