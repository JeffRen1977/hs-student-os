"""Step 3 verify: domain types match the Pydantic API schemas."""

from __future__ import annotations

import dataclasses

import pytest
from pydantic import BaseModel
from pydantic.alias_generators import to_camel

from app.domain.types import assessment as d_assessment
from app.domain.types import course as d_course
from app.domain.types import event as d_event
from app.domain.types import mastery as d_mastery
from app.domain.types import message as d_message
from app.domain.types import run as d_run
from app.domain.types import session as d_session
from app.domain.types import student as d_student
from app.domain.types import submission as d_submission
from app.domain.types import task as d_task
from app.schemas import (
    assessment,
    course,
    event,
    message,
    run,
    session,
    student,
    submission,
    task,
)

# (schema, domain type, fields only in the domain, fields only in the schema)
PAIRS: list[tuple[type[BaseModel], type, set[str], set[str]]] = [
    (student.Profile, d_student.Profile, set(), set()),
    (student.Goals, d_student.Goals, set(), set()),
    (student.Preferences, d_student.Preferences, set(), set()),
    (student.NotificationPreferences, d_student.NotificationPreferences, set(), set()),
    (student.Entitlements, d_student.Entitlements, set(), set()),
    (student.MasteryEntry, d_student.MasterySummary, set(), set()),
    (student.PredictionEntry, d_student.PredictionSummary, set(), set()),
    (student.TwinSummary, d_student.Student, set(), set()),
    # open_session_id is the internal one-OPEN-Session-per-Task guard.
    (task.Task, d_task.Task, {"open_session_id"}, set()),
    (task.TaskReason, d_task.TaskReason, set(), set()),
    # The domain keeps owner/course/version server-side; the API omits them on Session.
    # Pinned skills, completion inputs and timestamps stay server-side too.
    (
        session.Session,
        d_session.Session,
        {
            "student_id",
            "course_id",
            "version",
            "agent_skills",
            "has_accepted_assessment",
            "created_at",
            "updated_at",
            "server_hint_count",
        },
        # The API projects the pinned activity with its prompt and exposes the hint count.
        {"hint_count"},
    ),
    (session.CompletionEligibility, d_session.CompletionEligibility, set(), set()),
    (session.ContextVersion, d_session.ContextVersion, set(), set()),
    # Lease/cancel internals are never exposed to clients.
    (
        run.Run,
        d_run.Run,
        {
            "student_id",
            "cancel_requested",
            "lease_fencing_token",
            "lease_owner",
            "lease_expires_at",
            "dispatch_generation",
            "usage_tokens",
            "created_at",
            "updated_at",
        },
        set(),
    ),
    (run.InputRequest, d_run.InputRequest, set(), set()),
    (run.RunResult, d_run.RunResult, set(), set()),
    (run.RunError, d_run.RunError, set(), set()),
    # Hint/attempt counts are server records used by assessment, not client contract.
    (
        submission.Submission,
        d_submission.Submission,
        {"student_id", "server_hint_count", "prior_attempt_count"},
        set(),
    ),
    (submission.CreateSubmissionRequest, d_submission.SubmissionInput, set(), set()),
    (assessment.Assessment, d_assessment.Assessment, {"student_id"}, set()),
    # Mastery keeps its evidence contributions server-side (rebuild/regrade bookkeeping).
    (assessment.MasteryState, d_mastery.MasteryState, {"contributions"}, set()),
    (assessment.RubricResult, d_assessment.RubricResult, set(), set()),
    (assessment.HintUsage, d_assessment.HintUsage, set(), set()),
    (assessment.SkillEvidence, d_assessment.SkillEvidence, set(), set()),
    (assessment.Uncertainty, d_assessment.Uncertainty, set(), set()),
    (assessment.Provenance, d_assessment.Provenance, set(), set()),
    (event.Event, d_event.DomainEvent, set(), set()),
    # `status` is derived (a property on the domain type).
    (course.CatalogEntry, d_course.CourseCatalogEntry, set(), {"status"}),
    (message.Message, d_message.Message, {"student_id"}, set()),
    (course.AgentSummary, d_course.AgentConfig, {"description"}, set()),
]


@pytest.mark.parametrize(
    ("schema", "domain", "domain_only", "schema_only"),
    PAIRS,
    ids=[p[0].__name__ for p in PAIRS],
)
def test_fields_match(
    schema: type[BaseModel], domain: type, domain_only: set[str], schema_only: set[str]
) -> None:
    domain_fields = {f.name for f in dataclasses.fields(domain)}
    schema_fields = set(schema.model_fields)
    assert domain_fields - domain_only == schema_fields - schema_only
    # JSON names are the camelCase of the shared snake_case names.
    for name in schema_fields:
        assert schema.model_fields[name].alias in (None, to_camel(name))
