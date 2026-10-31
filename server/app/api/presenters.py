"""Domain → API schema projections. Internal fields (leases, fencing tokens, outbox ids,
pinned skills, owner ids where the contract omits them) are dropped here."""

from __future__ import annotations

from app.domain.course_service import CourseAgent, EnrolledCourse
from app.domain.types.course import AgentConfig, CourseCatalogEntry, CourseEnrollment
from app.domain.types.message import Message
from app.domain.types.run import Run
from app.domain.types.session import Session
from app.domain.types.student import Entitlements, NotificationPreferences, Student
from app.domain.types.submission import Submission
from app.domain.types.task import Task
from app.schemas import course as c
from app.schemas import message as m
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


def course_agent(a: CourseAgent) -> c.CourseAgentView:
    return c.CourseAgentView(
        course_id=a.course.course_id,
        agent_type=a.course.agent.agent_type,
        name=a.course.name,
        modes=list(a.course.agent.modes),
        supported_task_types=list(a.course.agent.supported_task_types),
        active_sessions=[session(x) for x in a.active_sessions],
        mastery_summary={
            k: st.MasteryEntry(
                level=v.level, independent_evidence_count=v.independent_evidence_count
            )
            for k, v in a.mastery_summary.items()
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
        reason=t.TaskReason(code=x.reason.code, source_event_ids=list(x.reason.source_event_ids)),
        student_locked=x.student_locked,
    )


def session(x: Session) -> s.Session:
    return s.Session(
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
