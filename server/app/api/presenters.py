"""Domain → API schema projections. Internal fields (leases, fencing tokens, outbox ids,
pinned skills, owner ids where the contract omits them) are dropped here."""

from __future__ import annotations

from app.domain.course_service import CourseAgent, EnrolledCourse
from app.domain.ports.content import SubjectPackRegistry
from app.domain.types.assessment import Assessment
from app.domain.types.course import AgentConfig, CourseCatalogEntry, CourseEnrollment
from app.domain.types.event import DomainEvent
from app.domain.types.mastery import MasteryState
from app.domain.types.message import Message
from app.domain.types.plan import Plan
from app.domain.types.run import Run
from app.domain.types.session import Session
from app.domain.types.student import Entitlements, NotificationPreferences, Student
from app.domain.types.submission import Submission
from app.domain.types.task import Task
from app.schemas import assessment as a
from app.schemas import course as c
from app.schemas import event as ev
from app.schemas import message as m
from app.schemas import plan as pl
from app.schemas import run as r
from app.schemas import session as s
from app.schemas import student as st
from app.schemas import submission as sb
from app.schemas import task as t


def _notifications(n: NotificationPreferences) -> st.NotificationPreferences:
    return st.NotificationPreferences(
        enabled=n.enabled,
        channels=list(n.channels),
        quiet_hours=(
            st.QuietHours(start=n.quiet_hours.start, end=n.quiet_hours.end)
            if n.quiet_hours
            else None
        ),
    )


def twin(student: Student) -> st.TwinSummary:
    p, g, pr = student.profile, student.goals, student.preferences
    return st.TwinSummary(
        student_id=student.student_id,
        version=student.version,
        profile=st.Profile(
            display_name=p.display_name,
            grade=p.grade,
            school=p.school,
            target_major=p.target_major,
            target_schools=list(p.target_schools),
        ),
        goals=st.Goals(sat_target=g.sat_target, ap_targets=dict(g.ap_targets)),
        preferences=st.Preferences(
            timezone=pr.timezone,
            weekly_available_minutes=pr.weekly_available_minutes,
            selected_courses=list(pr.selected_courses),
            notifications=_notifications(pr.notifications),
        ),
        mastery_summary={
            k: st.MasteryEntry(
                level=v.level, independent_evidence_count=v.independent_evidence_count
            )
            for k, v in student.mastery_summary.items()
        },
        prediction_summary={
            k: st.PredictionEntry(status=v.status, reason=v.reason)
            for k, v in student.prediction_summary.items()
        },
        latest_event_sequence=student.latest_event_sequence,
    )


def entitlements(e: Entitlements) -> st.Entitlements:
    return st.Entitlements(ap_courses=list(e.ap_courses), dsat=e.dsat, admissions=e.admissions)


def agent_summary(a: AgentConfig) -> c.AgentSummary:
    return c.AgentSummary(
        agent_type=a.agent_type,
        modes=list(a.modes),
        supported_task_types=list(a.supported_task_types),
    )


def catalog_entry(e: CourseCatalogEntry) -> c.CatalogEntry:
    return c.CatalogEntry(
        course_id=e.course_id,
        name=e.name,
        description=e.description,
        category=e.category,
        availability=e.availability,
        entitled=e.entitled,
        enrolled=e.enrolled,
        status=e.status,
        agent=agent_summary(e.agent),
    )


def enrollment(e: CourseEnrollment) -> c.Enrollment:
    return c.Enrollment(course_id=e.course_id, enrolled_at=e.enrolled_at, status=e.status)


def enrolled_course(e: EnrolledCourse) -> c.EnrolledCourse:
    return c.EnrolledCourse(
        course_id=e.course.course_id,
        name=e.course.name,
        enrolled_at=e.enrollment.enrolled_at,
        status=e.enrollment.status,
        agent=agent_summary(e.course.agent),
    )


def course_agent(ag: CourseAgent, packs: SubjectPackRegistry | None = None) -> c.CourseAgentView:
    return c.CourseAgentView(
        course_id=ag.course.course_id,
        agent_type=ag.course.agent.agent_type,
        name=ag.course.name,
        modes=list(ag.course.agent.modes),
        supported_task_types=list(ag.course.agent.supported_task_types),
        active_sessions=[session(x, packs) for x in ag.active_sessions],
        mastery_summary={
            k: st.MasteryEntry(
                level=v.level, independent_evidence_count=v.independent_evidence_count
            )
            for k, v in ag.mastery_summary.items()
        },
    )


def task(x: Task) -> t.Task:
    return t.Task(
        task_id=x.task_id,
        student_id=x.student_id,
        agent=x.agent,
        course_id=x.course_id,
        task_type=x.task_type,
        mode=x.mode,
        title=x.title,
        duration_min=x.duration_min,
        scheduled_date=x.scheduled_date,
        status=x.status,
        version=x.version,
        reason=t.TaskReason(
            code=x.reason.code,
            source_event_ids=list(x.reason.source_event_ids),
            explanation=x.reason.explanation,
        ),
        student_locked=x.student_locked,
        question_id=x.question_id,
        due_date=x.due_date,
        skip_reason=x.skip_reason,
    )


def session(x: Session, packs: SubjectPackRegistry | None = None) -> s.Session:
    activity = None
    if x.activity is not None and packs is not None:
        q = packs.question(x.course_id, x.activity.question_id)
        if q is not None and q.version == x.activity.question_version:
            activity = s.SessionActivity(
                question_id=q.question_id, question_version=q.version,
                topic=q.topic, prompt=q.prompt,
                items=[
                    s.ActivityItem(
                        item_id=i.item_id,
                        prompt=i.prompt,
                        choices=[
                            s.ActivityChoice(key=k, text=text)  # type: ignore[arg-type]
                            for k, text in i.choices
                        ],
                    )
                    for i in q.items
                ] if q.items is not None else None,
            )  # fmt: skip
    return s.Session(
        activity=activity,
        hint_count=x.server_hint_count,
        session_id=x.session_id,
        task_id=x.task_id,
        status=x.status,
        active_run_id=x.active_run_id,
        context_version=s.ContextVersion(
            pack=x.context_version.pack, workflow=x.context_version.workflow
        ),
        completion=s.CompletionEligibility(
            eligible=x.completion.eligible, reason=x.completion.reason
        ),
    )


def message(x: Message) -> m.Message:
    return m.Message(
        message_id=x.message_id,
        session_id=x.session_id,
        role=x.role,
        text=x.text,
        file_ids=list(x.file_ids),
        run_id=x.run_id,
        created_at=x.created_at,
        synthetic=x.synthetic,
    )


def submission(x: Submission) -> sb.Submission:
    return sb.Submission(
        submission_id=x.submission_id,
        session_id=x.session_id,
        question_id=x.question_id,
        question_version=x.question_version,
        answer=sb.Answer(text=x.answer.text, file_ids=list(x.answer.file_ids)),
        supersedes_submission_id=x.supersedes_submission_id,
        run_id=x.run_id,
        created_at=x.created_at,
    )


def run(x: Run) -> r.Run:
    return r.Run(
        run_id=x.run_id,
        session_id=x.session_id,
        status=x.status,
        kind=x.kind,
        submission_id=x.submission_id,
        message_id=x.message_id,
        attempt_count=x.attempt_count,
        input_request=(
            r.InputRequest(
                input_request_id=x.input_request.input_request_id,
                kind=x.input_request.kind,
                prompt=x.input_request.prompt,
            )
            if x.input_request
            else None
        ),
        result=(
            r.RunResult(
                message_id=x.result.message_id,
                assessment_id=x.result.assessment_id,
                plan_id=x.result.plan_id,
            )
            if x.result
            else None
        ),
        error=r.RunError(code=x.error.code, retryable=x.error.retryable) if x.error else None,
    )


def assessment(x: Assessment) -> a.Assessment:
    return a.Assessment(
        assessment_id=x.assessment_id,
        submission_id=x.submission_id,
        session_id=x.session_id,
        run_id=x.run_id,
        status=x.status,
        question_version=x.question_version,
        rubric_version=x.rubric_version,
        rubric_results=[
            a.RubricResult(
                criterion_id=r.criterion_id,
                earned=r.earned,
                possible=r.possible,
                evidence_refs=list(r.evidence_refs),
                assessable=r.assessable,
            )
            for r in x.rubric_results
        ],
        hint_usage=a.HintUsage(
            server_hint_count=x.hint_usage.server_hint_count,
            self_reported_help=x.hint_usage.self_reported_help,
        ),
        skill_evidence=[
            a.SkillEvidence(skill_id=e.skill_id, observation=e.observation)
            for e in x.skill_evidence
        ],
        uncertainty=a.Uncertainty(level=x.uncertainty.level, reasons=list(x.uncertainty.reasons)),
        provenance=a.Provenance(
            model_version=x.provenance.model_version,
            workflow_version=x.provenance.workflow_version,
            tool_result_ids=list(x.provenance.tool_result_ids),
        ),
        supersedes_assessment_id=x.supersedes_assessment_id,
        question_id=x.question_id,
        rubric_id=x.rubric_id,
        feedback=x.feedback,
        created_at=x.created_at,
    )


def mastery(m: MasteryState) -> a.MasteryState:
    return a.MasteryState(
        skill_id=m.skill_id,
        course_id=m.course_id,
        level=m.level,
        independent_evidence_count=m.independent_evidence_count,
        evidence_count=m.evidence_count,
        coverage=m.coverage,
        uncertainty=m.uncertainty,
        updated_at=m.updated_at,
        rule_version=m.rule_version,
    )


def event(e: DomainEvent) -> ev.Event:
    """Filtered projection: only the payload fields declared for the event type survive, so
    internal keys (outbox ids, model output, tool arguments) can never reach a client."""
    model = ev.PAYLOAD_TYPES[e.type]
    allowed = {f.alias or name for name, f in model.model_fields.items()}
    payload = {k: v for k, v in e.payload.items() if k in allowed}
    return ev.Event(
        event_id=e.event_id,
        sequence=e.sequence,
        schema_version=e.schema_version,
        student_id=e.student_id,
        session_id=e.session_id,
        run_id=e.run_id,
        type=e.type,
        occurred_at=e.occurred_at,
        causation_id=e.causation_id,
        payload=model.model_validate(payload).model_dump(mode="json", by_alias=True),
    )


def plan(p: Plan) -> pl.Plan:
    return pl.Plan(
        plan_id=p.plan_id,
        run_id=p.run_id,
        rule_version=p.rule_version,
        local_date=p.local_date,
        horizon_end=p.horizon_end,
        weekly_minutes=p.weekly_minutes,
        daily_minutes=p.daily_minutes,
        evidence_available=p.evidence_available,
        entries=[
            pl.PlanEntry(
                task_id=e.task_id,
                course_id=e.course_id,
                duration_min=e.duration_min,
                previous_date=e.previous_date,
                scheduled_date=e.scheduled_date,
                priority=e.priority,
                placement=e.placement,
                explanation=e.explanation,
                source_event_ids=list(e.source_event_ids),
            )
            for e in p.entries
        ],
        created_at=p.created_at,
    )
