"""Course package authoring and the platform review gate (Step 26, API.md §6.3).

`/api/authoring/*` — authors of one organization: upload, submit, read their own packages.
`/api/review/*`    — platform reviewers: queue, read, approve, reject, activate, retire.

Students are not platform members and get 403 on all of these routes. Another
organization's packages return 404. Every POST needs an Idempotency-Key.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse

from app.api.dependencies.auth import Platform, ServicesDep
from app.api.dependencies.commands import IdempotencyKeyHeader, command_key
from app.api.responses import respond
from app.api.routes.params import CoursePath
from app.domain.errors import DomainError, ErrorCode
from app.domain.package_service import ApproveInput
from app.domain.types.course_metrics import MIN_COHORT, CourseMetrics
from app.domain.types.package import PackageStatus, PackageVersion, ValidationReport
from app.schemas import package as pk
from app.schemas.package import CoursePackage, StarterTask

authoring = APIRouter(prefix="/api/authoring", tags=["authoring"])
review = APIRouter(prefix="/api/review", tags=["review"])

VersionPath = Annotated[str, Path(pattern=r"^\d+\.\d+\.\d+$")]
DEFAULT_QUEUE = (PackageStatus.SUBMITTED, PackageStatus.APPROVED)


def _report(r: ValidationReport) -> pk.ValidationReportView:
    return pk.ValidationReportView(
        valid=r.valid,
        validator_version=r.validator_version,
        errors=[pk.PackageIssueView(path=i.path, code=i.code, message=i.message) for i in r.errors],
        evaluation=pk.EvaluationView(
            auto_cases=r.evaluation.auto_cases,
            auto_passed=r.evaluation.auto_passed,
            model_cases=r.evaluation.model_cases,
            failures=list(r.evaluation.failures),
        ),
    )


def version_view(v: PackageVersion, *, with_package: bool = False) -> pk.PackageVersionView:
    rv = v.review
    return pk.PackageVersionView(
        course_id=v.course_id,
        version=v.version,
        title=v.title,
        status=v.status.value,
        org_id=v.org_id,
        content_hash=v.content_hash,
        uploaded_by=v.uploaded_by,
        created_at=v.created_at,
        updated_at=v.updated_at,
        report=_report(v.report),
        review=None
        if rv is None
        else pk.ReviewDecisionView(
            reviewer_id=rv.reviewer_id,
            decision=rv.decision.value,  # type: ignore[arg-type]
            decided_at=rv.decided_at,
            notes=rv.notes,
            license_attested=rv.license_attested,
            model_evaluation_attested=rv.model_evaluation_attested,
        ),
        history=[
            pk.StatusChangeView(
                from_status=h.from_status.value if h.from_status else None,
                to_status=h.to_status.value,
                actor_id=h.actor_id,
                at=h.at,
                notes=h.notes,
            )
            for h in v.history
        ],
        package=json.loads(v.package_json) if with_package else None,
    )


def _status(created: bool) -> int:
    return 201 if created else 200


# ---- Authoring ----------------------------------------------------------------------------------


@authoring.post("/packages", response_model=pk.PackageVersionView, status_code=201)
async def upload_package(
    body: pk.PackageUploadRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.packages.upload(actor, body.package, cmd)
    return respond(
        version_view(outcome.value), status=_status(outcome.created), replayed=outcome.replayed
    )


@authoring.get("/packages", response_model=pk.PackageVersionList)
async def list_own_packages(actor: Platform, services: ServicesDep) -> JSONResponse:
    versions = await services.packages.list_own(actor)
    return respond(pk.PackageVersionList(versions=[version_view(v) for v in versions]))


@authoring.get("/packages/{course_id}/versions/{version}", response_model=pk.PackageVersionView)
async def get_own_package(
    course_id: CoursePath, version: VersionPath, actor: Platform, services: ServicesDep
) -> JSONResponse:
    v = await services.packages.get_own(actor, course_id, version)
    return respond(version_view(v, with_package=True))


@authoring.post(
    "/packages/{course_id}/versions/{version}/submit", response_model=pk.PackageVersionView
)
async def submit_package(
    course_id: CoursePath,
    version: VersionPath,
    body: pk.EmptyCommand,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.packages.submit(actor, course_id, version, cmd)
    return respond(version_view(outcome.value), replayed=outcome.replayed)


def _preview_task(t: StarterTask) -> pk.PreviewStarterTask:
    return pk.PreviewStarterTask(
        question_id=t.question_id,
        title=t.title,
        task_type=t.task_type,
        mode=t.mode,
        duration_min=t.duration_min,
    )


def preview_view(v: PackageVersion) -> pk.PackagePreview:
    if not v.report.valid:
        raise DomainError(ErrorCode.PACKAGE_INVALID, "Fix the validator errors to preview.")
    pkg = CoursePackage.model_validate(json.loads(v.package_json))
    materials = {m.material_id: m for m in pkg.materials}
    return pk.PackagePreview(
        course_id=pkg.manifest.course_id,
        version=pkg.manifest.version,
        name=pkg.manifest.name,
        description=pkg.manifest.description,
        skills=[pk.PreviewSkill(skill_id=s.skill_id, name=s.name) for s in pkg.skills],
        starter_tasks=[_preview_task(t) for t in pkg.starter_tasks],
        practice_sequence=[_preview_task(t) for t in pkg.practice_sequence],
        questions=[
            pk.PreviewQuestion(
                question_id=q.question_id,
                version=q.version,
                topic=q.topic,
                prompt=q.prompt,
                items=[
                    pk.PreviewItem(
                        item_id=i.item_id,
                        prompt=i.prompt,
                        choices=[pk.PreviewChoice(key=c.key, text=c.text) for c in i.choices],
                    )
                    for i in q.items
                ]
                if q.items is not None
                else None,
                sources=[
                    pk.PreviewSource(
                        material_id=mid, title=materials[mid].title, text=materials[mid].text
                    )
                    for mid in q.source_material_ids
                ]
                or None,
            )
            for q in pkg.questions
        ],
    )


def metrics_view(m: CourseMetrics) -> pk.CourseMetricsView:
    if m.suppressed:
        return pk.CourseMetricsView(
            course_id=m.course_id, suppressed=True, minimum_cohort=MIN_COHORT
        )
    criteria = []
    for key, t in sorted(m.criteria.items()):
        rubric_id, _, criterion_id = key.partition(":")
        if t.count == 0:
            continue
        criteria.append(
            pk.CriterionMetricView(
                rubric_id=rubric_id,
                criterion_id=criterion_id,
                count=t.count,
                average_earned=round(t.earned / t.count, 2),
                max_points=round(t.possible / t.count, 2),
            )
        )
    return pk.CourseMetricsView(
        course_id=m.course_id,
        suppressed=False,
        minimum_cohort=MIN_COHORT,
        students=m.students,
        assessments=m.assessments,
        by_status=dict(m.by_status),
        criteria=criteria,
        updated_at=m.updated_at,
    )


@authoring.get("/packages/{course_id}/versions/{version}/preview", response_model=pk.PackagePreview)
async def preview_own_package(
    course_id: CoursePath, version: VersionPath, actor: Platform, services: ServicesDep
) -> JSONResponse:
    v = await services.packages.get_own(actor, course_id, version)
    return respond(preview_view(v))


@authoring.get("/courses/{course_id}/metrics", response_model=pk.CourseMetricsView)
async def course_metrics(
    course_id: CoursePath, actor: Platform, services: ServicesDep
) -> JSONResponse:
    return respond(metrics_view(await services.packages.course_metrics(actor, course_id)))


@review.get("/packages/{course_id}/versions/{version}/preview", response_model=pk.PackagePreview)
async def preview_package_for_review(
    course_id: CoursePath, version: VersionPath, actor: Platform, services: ServicesDep
) -> JSONResponse:
    v = await services.packages.get_for_review(actor, course_id, version)
    return respond(preview_view(v))


# ---- Platform review ---------------------------------------------------------------------------


@review.get("/packages", response_model=pk.PackageVersionList)
async def review_queue(
    actor: Platform,
    services: ServicesDep,
    status: Annotated[list[PackageStatus] | None, Query()] = None,
) -> JSONResponse:
    versions = await services.packages.review_queue(actor, status or list(DEFAULT_QUEUE))
    return respond(pk.PackageVersionList(versions=[version_view(v) for v in versions]))


@review.get("/packages/{course_id}/versions/{version}", response_model=pk.PackageVersionView)
async def review_package(
    course_id: CoursePath, version: VersionPath, actor: Platform, services: ServicesDep
) -> JSONResponse:
    v = await services.packages.get_for_review(actor, course_id, version)
    return respond(version_view(v, with_package=True))


@review.post(
    "/packages/{course_id}/versions/{version}/approve", response_model=pk.PackageVersionView
)
async def approve_package(
    course_id: CoursePath,
    version: VersionPath,
    body: pk.ReviewApproveRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    inp = ApproveInput(
        notes=body.notes,
        license_attested=body.license_attested,
        model_evaluation_attested=body.model_evaluation_attested,
    )
    outcome = await services.packages.approve(actor, course_id, version, inp, cmd)
    return respond(version_view(outcome.value), replayed=outcome.replayed)


@review.post(
    "/packages/{course_id}/versions/{version}/reject", response_model=pk.PackageVersionView
)
async def reject_package(
    course_id: CoursePath,
    version: VersionPath,
    body: pk.ReviewRejectRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.packages.reject(actor, course_id, version, body.notes, cmd)
    return respond(version_view(outcome.value), replayed=outcome.replayed)


@review.post(
    "/packages/{course_id}/versions/{version}/activate", response_model=pk.PackageVersionView
)
async def activate_package(
    course_id: CoursePath,
    version: VersionPath,
    body: pk.EmptyCommand,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.packages.activate(actor, course_id, version, cmd)
    return respond(version_view(outcome.value), replayed=outcome.replayed)


@review.post("/courses/{course_id}/retire", response_model=pk.PackageVersionView)
async def retire_course(
    course_id: CoursePath,
    body: pk.RetireRequest,
    request: Request,
    actor: Platform,
    services: ServicesDep,
    idempotency_key: IdempotencyKeyHeader = None,
) -> JSONResponse:
    cmd = command_key(request, idempotency_key, body)
    outcome = await services.packages.retire(actor, course_id, body.notes, cmd)
    return respond(version_view(outcome.value), replayed=outcome.replayed)
