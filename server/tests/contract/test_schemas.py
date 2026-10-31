"""Step 2.10: API.md examples validate; forbidden client mutations are rejected."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from app.schemas import (
    assessment,
    common,
    course,
    error,
    event,
    run,
    session,
    student,
    submission,
    task,
)
from tests.contract import api_examples as ex

VALID_EXAMPLES: list[tuple[type[BaseModel], dict[str, Any]]] = [
    (student.TwinSummary, ex.TWIN),
    (student.Entitlements, ex.ENTITLEMENTS),
    (course.PackSummary, ex.PACK),
    (task.Task, ex.TASK),
    (session.Session, ex.SESSION),
    (run.Run, ex.RUN),
    (submission.CreateSubmissionRequest, ex.SUBMISSION_REQUEST),
    (submission.SubmissionAccepted, ex.SUBMISSION_ACCEPTED),
    (submission.CreateMessageRequest, ex.MESSAGE_REQUEST),
    (submission.MessageAccepted, ex.MESSAGE_ACCEPTED),
    (run.RunInputRequest, ex.RUN_INPUT),
    (assessment.Assessment, ex.ASSESSMENT),
    (event.Event, ex.EVENT),
    (event.EventPage, ex.EVENT_PAGE),
    (course.CatalogResponse, ex.CATALOG),
    (course.Enrollment, ex.ENROLLMENT),
    (course.EnrolledCoursesResponse, ex.ENROLLED),
    (course.CourseAgentView, ex.COURSE_AGENT),
    (error.ErrorEnvelope, ex.ERROR),
    (course.EnrollRequest, {"courseId": "calc_bc"}),
    (session.CreateSessionRequest, {"taskId": "task_calc_01"}),
    (common.EmptyCommand, {}),
]


@pytest.mark.parametrize(
    ("model", "payload"), VALID_EXAMPLES, ids=lambda v: getattr(v, "__name__", "")
)
def test_api_examples_validate_and_round_trip(
    model: type[BaseModel], payload: dict[str, Any]
) -> None:
    parsed = model.model_validate(payload)
    dumped = parsed.model_dump(mode="json", by_alias=True, exclude_unset=True)
    assert model.model_validate(dumped) == parsed


@pytest.mark.parametrize(
    ("model", "payload"), VALID_EXAMPLES, ids=lambda v: getattr(v, "__name__", "")
)
def test_unknown_top_level_fields_are_rejected(
    model: type[BaseModel], payload: dict[str, Any]
) -> None:
    with pytest.raises(ValidationError, match="extra"):
        model.model_validate({**payload, "unexpectedField": 1})


def _with(base: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    data = copy.deepcopy(base)
    *parents, leaf = path.split(".")
    node = data
    for key in parents:
        node = node[key]
    node[leaf] = value
    return data


# ---- Client score / assessment forgery on submissions ----------------------------------


@pytest.mark.parametrize(
    "forged_field",
    [
        "scoreDelta",
        "score",
        "outcome",
        "status",
        "assessmentStatus",
        "mastery",
        "earned",
        "skillEvidence",
        "toolResults",
        "studentId",
    ],
)
def test_submission_rejects_client_authority_fields(forged_field: str) -> None:
    with pytest.raises(ValidationError):
        submission.CreateSubmissionRequest.model_validate(
            {**ex.SUBMISSION_REQUEST, forged_field: "accepted"}
        )


def test_submission_answer_rejects_nested_forgery() -> None:
    with pytest.raises(ValidationError):
        submission.CreateSubmissionRequest.model_validate(
            _with(ex.SUBMISSION_REQUEST, "answer.verified", True)
        )


def test_message_rejects_hint_count_override() -> None:
    with pytest.raises(ValidationError):
        submission.CreateMessageRequest.model_validate({**ex.MESSAGE_REQUEST, "hintCount": 0})


# ---- Twin PATCH whitelist ---------------------------------------------------------------


@pytest.mark.parametrize(
    "forbidden",
    [
        {"studentId": "stu_beth"},
        {"entitlements": {"apCourses": ["apush"]}},
        {"subscriptions": {"dsat": True}},
        {"masterySummary": {}},
        {"predictionSummary": {"calc_bc": {"status": "unavailable", "reason": "x"}}},
        {"version": 9},
        {"email": "x@example.test"},
        {"profile": {"email": "x@example.test"}},
        {"preferences": {"entitlements": ["apush"]}},
        {"goals": {"predicted": 4.8}},
    ],
)
def test_twin_patch_rejects_non_whitelisted_fields(forbidden: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        student.TwinPatch.model_validate(forbidden)


def test_twin_patch_accepts_whitelisted_leaf_fields() -> None:
    patch = student.TwinPatch.model_validate(
        {
            "profile": {"displayName": "Al", "targetSchools": ["Synthetic U"]},
            "goals": {"satTarget": 1500, "apTargets": {"calc_bc": 5}},
            "preferences": {"timezone": "America/Chicago", "selectedCourses": ["calc_bc"]},
        }
    )
    assert patch.preferences is not None
    assert patch.preferences.selected_courses == ["calc_bc"]


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"profile": {"grade": 13}},
        {"goals": {"satTarget": 1601}},
        {"goals": {"satTarget": 1555}},
        {"goals": {"apTargets": {"calc_bc": 6}}},
        {"preferences": {"timezone": "PST"}},
        {"preferences": {"timezone": "Mars/Olympus"}},
        {"preferences": {"weeklyAvailableMinutes": -1}},
        {"preferences": {"selectedCourses": ["calc_bc", "calc_bc"]}},
        {"preferences": {"selectedCourses": ["Calc BC"]}},
        {"preferences": {"notifications": {"enabled": False, "channels": ["email"]}}},
        {"preferences": {"notifications": {"quietHours": {"start": "25:00", "end": "08:00"}}}},
    ],
)
def test_twin_patch_field_constraints(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        student.TwinPatch.model_validate(bad)


def test_twin_rejects_numeric_prediction() -> None:
    with pytest.raises(ValidationError):
        student.TwinSummary.model_validate(
            _with(ex.TWIN, "predictionSummary.calc_bc", {"status": "available", "reason": "4.5"})
        )


# ---- Task PATCH -------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["COMPLETED", "IN_PROGRESS", "PLANNED"])
def test_task_patch_cannot_complete_or_start(status: str) -> None:
    with pytest.raises(ValidationError):
        task.TaskPatchRequest.model_validate({"status": status})


def test_task_patch_allows_skip_reschedule_lock() -> None:
    p = task.TaskPatchRequest.model_validate(
        {"status": "SKIPPED", "scheduledDate": "2026-11-02", "studentLocked": True}
    )
    assert p.status == "SKIPPED"


@pytest.mark.parametrize("field", ["title", "courseId", "agent", "version", "reason", "taskType"])
def test_task_patch_rejects_server_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        task.TaskPatchRequest.model_validate({field: "x"})


# ---- Commands cannot redirect scope -----------------------------------------------------


@pytest.mark.parametrize("extra", [{"courseId": "apush"}, {"agent": "DSAT"}, {"tools": ["x"]}])
def test_create_session_derives_course_from_task(extra: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        session.CreateSessionRequest.model_validate({"taskId": "task_calc_01", **extra})


def test_empty_commands_reject_any_body() -> None:
    with pytest.raises(ValidationError):
        common.EmptyCommand.model_validate({"status": "COMPLETED"})


def test_run_input_cannot_inject_assessment() -> None:
    with pytest.raises(ValidationError):
        run.RunInputRequest.model_validate(_with(ex.RUN_INPUT, "value.assessment", "accepted"))


def test_requests_are_immutable() -> None:
    req = session.CreateSessionRequest.model_validate({"taskId": "task_calc_01"})
    with pytest.raises(ValidationError):
        req.task_id = "other"  # type: ignore[misc]


# ---- Events cannot be published by clients ---------------------------------------------


def test_no_request_model_accepts_an_event() -> None:
    request_models = [
        m
        for m in vars(common).values()
        if isinstance(m, type)
        and issubclass(m, common.RequestModel)
        and m is not common.RequestModel
    ]
    for module in (student, task, session, run, submission, course):
        request_models += [
            m
            for m in vars(module).values()
            if isinstance(m, type)
            and issubclass(m, common.RequestModel)
            and m is not common.RequestModel
        ]
    assert request_models, "expected to discover request models"
    for model in set(request_models):
        with pytest.raises(ValidationError):
            model.model_validate(ex.EVENT)


@pytest.mark.parametrize(
    "payload",
    [
        {"assessmentId": "assess_01"},  # missing status
        {"assessmentId": "assess_01", "status": "accepted", "rawModelReasoning": "..."},
        {"assessmentId": "assess_01", "status": "graded"},
    ],
)
def test_event_payload_is_typed_per_event(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        event.Event.model_validate({**ex.EVENT, "payload": payload})


def test_event_type_must_be_known() -> None:
    with pytest.raises(ValidationError):
        event.Event.model_validate({**ex.EVENT, "type": "skill.weak"})


def test_event_timestamps_must_be_utc() -> None:
    with pytest.raises(ValidationError):
        event.Event.model_validate({**ex.EVENT, "occurredAt": "2026-10-29T10:00:00-07:00"})
    with pytest.raises(ValidationError):
        event.Event.model_validate({**ex.EVENT, "occurredAt": "2026-10-29T17:00:00"})


def test_planner_events_have_null_session_and_run() -> None:
    planner = {
        **ex.EVENT,
        "sessionId": None,
        "runId": None,
        "type": "plan.updated",
        "causationId": None,
        "payload": {"planId": "plan_01", "changedTaskIds": ["task_calc_01"]},
    }
    assert event.Event.model_validate(planner).typed_payload()


# ---- Malformed relationships -----------------------------------------------------------


@pytest.mark.parametrize(
    "mutation",
    [
        {"sessionId": None},  # only PLANNING runs may be session-less
        {"status": "WAITING_INPUT"},  # without inputRequest
        {"inputRequest": {"inputRequestId": "i1", "kind": "OCR_CONFIRMATION", "prompt": "?"}},
        {"result": {"assessmentId": "assess_01"}},  # result on a QUEUED run
        {"error": {"code": "MODEL_TIMEOUT", "retryable": True}},  # error on a QUEUED run
        {"submissionId": None},  # assessment run without a submission
        {"attemptCount": -1},
        {"status": "DONE"},
    ],
)
def test_run_relationships(mutation: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        run.Run.model_validate({**ex.RUN, **mutation})


def test_planning_run_without_session_is_valid() -> None:
    run.Run.model_validate({**ex.RUN, "sessionId": None, "kind": "PLANNING", "submissionId": None})


def test_session_relationships() -> None:
    with pytest.raises(ValidationError):
        session.Session.model_validate(
            {**ex.SESSION, "status": "COMPLETED", "activeRunId": "run_01"}
        )
    with pytest.raises(ValidationError):
        session.Session.model_validate(
            {**ex.SESSION, "completion": {"eligible": True, "reason": "run_in_progress"}}
        )


@pytest.mark.parametrize(
    "mutation",
    [
        ("rubricResults", [{"criterionId": "c", "earned": 2, "possible": 1, "evidenceRefs": []}]),
        ("status", "insufficient_evidence"),  # with non-empty skillEvidence
        (
            "skillEvidence",
            [{"skillId": "calc_bc.function-composition", "observation": "correct_independent"}],
        ),  # hint count is 1
        ("status", "partially_accepted"),
    ],
)
def test_assessment_integrity(mutation: tuple[str, Any]) -> None:
    key, value = mutation
    with pytest.raises(ValidationError):
        assessment.Assessment.model_validate({**ex.ASSESSMENT, key: value})


def test_insufficient_evidence_assessment_without_evidence_is_valid() -> None:
    a = assessment.Assessment.model_validate(
        {**ex.ASSESSMENT, "status": "insufficient_evidence", "skillEvidence": []}
    )
    assert a.status.value == "insufficient_evidence"


# ---- Common primitives ------------------------------------------------------------------


@pytest.mark.parametrize("key", ["a" * 15, "has space in it!!", "x" * 129, "ключ-идемпотентности"])
def test_idempotency_key_format(key: str) -> None:
    from pydantic import TypeAdapter

    with pytest.raises(ValidationError):
        TypeAdapter(common.IdempotencyKey).validate_python(key)


def test_if_match_parsing() -> None:
    assert common.parse_if_match('"3"') == 3
    assert common.format_etag(3) == '"3"'
    for bad in ("3", 'W/"3"', '"abc"', '""'):
        with pytest.raises(ValueError):
            common.parse_if_match(bad)


def test_page_query_limits() -> None:
    assert common.PageQuery().limit == 50
    with pytest.raises(ValidationError):
        common.PageQuery(limit=101)
    with pytest.raises(ValidationError):
        common.PageQuery(limit=0)


def test_every_error_code_has_an_http_status() -> None:
    assert set(error.ERROR_STATUS) == set(error.ErrorCode)
