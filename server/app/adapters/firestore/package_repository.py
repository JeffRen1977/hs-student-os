"""Course packages and platform members (BACKEND.md §3, Step 26).

Layout (outside every student's subtree, so no package path can reach student data):

    packageCourses/{courseId}                    ownership + active pointer
    packageVersions/{courseId}@{version}         one version: status, package, report, audit
    platformMembers/{uid}                        author (with orgId) or platform reviewer
    platformMembers/{uid}/idempotency/{keyHash}  command replay records of that member
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from app.adapters.firestore.course_metrics_repository import metrics_from_doc, metrics_path
from app.adapters.firestore.documents import Doc, DocTxn, DocumentStore, Filter, QuerySpec
from app.domain.ports.packages import PackageTx
from app.domain.types.common import IdempotencyRecord
from app.domain.types.course_metrics import CourseMetrics
from app.domain.types.package import (
    CourseState,
    EvaluationSummary,
    PackageCourse,
    PackageIssue,
    PackageStatus,
    PackageVersion,
    PlatformMember,
    ReviewDecision,
    StatusChange,
    ValidationReport,
    semver_key,
)

COURSES = "packageCourses"
VERSIONS = "packageVersions"
MEMBERS = "platformMembers"
QUERY_LIMIT = 500


def _id(value: str) -> str:
    if not value or "/" in value:
        raise ValueError("invalid document id")
    return value


def course_path(course_id: str) -> str:
    return f"{COURSES}/{_id(course_id)}"


def version_path(course_id: str, version: str) -> str:
    return f"{VERSIONS}/{_id(course_id)}@{_id(version)}"


def member_path(uid: str) -> str:
    return f"{MEMBERS}/{_id(uid)}"


# ---- Serialization ----------------------------------------------------------------------------


def report_to_doc(r: ValidationReport) -> Doc:
    return {
        "validatorVersion": r.validator_version,
        "errors": [{"path": i.path, "code": i.code, "message": i.message} for i in r.errors],
        "evaluation": {
            "autoCases": r.evaluation.auto_cases,
            "autoPassed": r.evaluation.auto_passed,
            "modelCases": r.evaluation.model_cases,
            "failures": list(r.evaluation.failures),
        },
    }


def report_from_doc(d: Doc) -> ValidationReport:
    ev = d.get("evaluation", {})
    return ValidationReport(
        validator_version=d["validatorVersion"],
        errors=tuple(
            PackageIssue(path=e["path"], code=e["code"], message=e["message"]) for e in d["errors"]
        ),
        evaluation=EvaluationSummary(
            auto_cases=int(ev.get("autoCases", 0)),
            auto_passed=int(ev.get("autoPassed", 0)),
            model_cases=int(ev.get("modelCases", 0)),
            failures=tuple(ev.get("failures", [])),
        ),
    )


def version_to_doc(v: PackageVersion) -> Doc:
    review = v.review
    return {
        "courseId": v.course_id,
        "version": v.version,
        "orgId": v.org_id,
        "status": v.status.value,
        "title": v.title,
        "packageJson": v.package_json,
        "contentHash": v.content_hash,
        "report": report_to_doc(v.report),
        "uploadedBy": v.uploaded_by,
        "createdAt": v.created_at,
        "updatedAt": v.updated_at,
        "review": None
        if review is None
        else {
            "reviewerId": review.reviewer_id,
            "decision": review.decision.value,
            "decidedAt": review.decided_at,
            "notes": review.notes,
            "licenseAttested": review.license_attested,
            "modelEvaluationAttested": review.model_evaluation_attested,
        },
        "history": [
            {
                "from": h.from_status.value if h.from_status else None,
                "to": h.to_status.value,
                "actorId": h.actor_id,
                "at": h.at,
                "notes": h.notes,
            }
            for h in v.history
        ],
    }


def version_from_doc(d: Doc) -> PackageVersion:
    r = d.get("review")
    return PackageVersion(
        course_id=d["courseId"],
        version=d["version"],
        org_id=d["orgId"],
        status=PackageStatus(d["status"]),
        title=d.get("title", ""),
        package_json=d["packageJson"],
        content_hash=d["contentHash"],
        report=report_from_doc(d["report"]),
        uploaded_by=d["uploadedBy"],
        created_at=d["createdAt"],
        updated_at=d["updatedAt"],
        review=None
        if r is None
        else ReviewDecision(
            reviewer_id=r["reviewerId"],
            decision=PackageStatus(r["decision"]),
            decided_at=r["decidedAt"],
            notes=r.get("notes", ""),
            license_attested=bool(r.get("licenseAttested", False)),
            model_evaluation_attested=bool(r.get("modelEvaluationAttested", False)),
        ),
        history=tuple(
            StatusChange(
                from_status=PackageStatus(h["from"]) if h.get("from") else None,
                to_status=PackageStatus(h["to"]),
                actor_id=h["actorId"],
                at=h["at"],
                notes=h.get("notes", ""),
            )
            for h in d.get("history", [])
        ),
    )


def course_to_doc(c: PackageCourse) -> Doc:
    return {
        "courseId": c.course_id,
        "orgId": c.org_id,
        "state": c.state.value,
        "activeVersion": c.active_version,
        "createdAt": c.created_at,
        "updatedAt": c.updated_at,
    }


def course_from_doc(d: Doc) -> PackageCourse:
    return PackageCourse(
        course_id=d["courseId"],
        org_id=d["orgId"],
        state=CourseState(d["state"]),
        active_version=d.get("activeVersion"),
        created_at=d["createdAt"],
        updated_at=d["updatedAt"],
    )


def _sorted(versions: list[PackageVersion]) -> list[PackageVersion]:
    return sorted(versions, key=lambda v: (v.course_id, semver_key(v.version)))


# ---- Stores -------------------------------------------------------------------------------------


class FirestorePackageCourseStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, course_id: str) -> PackageCourse | None:
        doc = await self._txn.get(course_path(course_id))
        return course_from_doc(doc) if doc else None

    def save(self, course: PackageCourse) -> None:
        self._txn.set(course_path(course.course_id), course_to_doc(course))


class FirestorePackageVersionStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, course_id: str, version: str) -> PackageVersion | None:
        doc = await self._txn.get(version_path(course_id, version))
        return version_from_doc(doc) if doc else None

    async def _query(self, flt: Filter) -> list[PackageVersion]:
        docs = await self._txn.query(VERSIONS, QuerySpec(filters=(flt,), limit=QUERY_LIMIT))
        return _sorted([version_from_doc(d) for d in docs])

    async def list_for_course(self, course_id: str) -> Sequence[PackageVersion]:
        return await self._query(Filter("courseId", "==", course_id))

    async def list_for_org(self, org_id: str) -> Sequence[PackageVersion]:
        return await self._query(Filter("orgId", "==", org_id))

    async def list_by_status(self, statuses: Sequence[PackageStatus]) -> Sequence[PackageVersion]:
        return await self._query(Filter("status", "in", [s.value for s in statuses]))

    def save(self, version: PackageVersion) -> None:
        self._txn.set(version_path(version.course_id, version.version), version_to_doc(version))


class FirestorePlatformIdempotencyStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    @staticmethod
    def _path(actor_id: str, key_hash: str) -> str:
        return f"{member_path(actor_id)}/idempotency/{_id(key_hash)}"

    async def get(self, actor_id: str, key_hash: str) -> IdempotencyRecord | None:
        doc = await self._txn.get(self._path(actor_id, key_hash))
        if doc is None:
            return None
        return IdempotencyRecord(
            key_hash=doc["keyHash"],
            scope=doc["scope"],
            request_digest=doc["requestDigest"],
            resource_type=doc["resourceType"],
            resource_id=doc["resourceId"],
            response_status=int(doc["responseStatus"]),
            created_at=doc["createdAt"],
        )

    def save(self, actor_id: str, r: IdempotencyRecord) -> None:
        self._txn.set(
            self._path(actor_id, r.key_hash),
            {
                "keyHash": r.key_hash,
                "scope": r.scope,
                "requestDigest": r.request_digest,
                "resourceType": r.resource_type,
                "resourceId": r.resource_id,
                "responseStatus": r.response_status,
                "createdAt": r.created_at,
            },
        )


class FirestoreCourseMetricsReader:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, course_id: str) -> CourseMetrics | None:
        doc = await self._txn.get(metrics_path(course_id))
        return metrics_from_doc(doc) if doc else None


class FirestorePackageTx:
    def __init__(self, txn: DocTxn) -> None:
        self.courses = FirestorePackageCourseStore(txn)
        self.versions = FirestorePackageVersionStore(txn)
        self.idempotency = FirestorePlatformIdempotencyStore(txn)
        self.metrics = FirestoreCourseMetricsReader(txn)


class DocumentPackageUnitOfWork:
    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    async def transaction[T](self, fn: Callable[[PackageTx], Awaitable[T]]) -> T:
        async def body(txn: DocTxn) -> T:
            return await fn(FirestorePackageTx(txn))

        return await self._store.run_transaction(body)


class FirestorePlatformDirectory:
    """`platformMembers/{uid}`: provisioned by platform operators (seed script locally).
    A uid that is not listed is not an author, reviewer or admin."""

    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    async def resolve(self, uid: str) -> PlatformMember | None:
        async def body(txn: DocTxn) -> Doc | None:
            return await txn.get(member_path(uid))

        doc: dict[str, Any] | None = await self._store.run_transaction(body)
        if doc is None or doc.get("role") not in ("author", "platform_reviewer", "admin"):
            return None
        return PlatformMember(uid=uid, role=str(doc["role"]), org_id=doc.get("orgId"))
