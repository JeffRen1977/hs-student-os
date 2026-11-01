from __future__ import annotations

from typing import Any

from app.adapters.firestore import paths
from app.adapters.firestore.documents import Doc, DocTxn, Filter
from app.adapters.firestore.paging import paged_query
from app.domain.types.actor import ActorContext
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
from app.domain.types.common import PageRequest, PaginatedResponse
from app.domain.types.mastery import MasteryContribution, MasteryState
from app.domain.types.student import MasteryLevel


def assessment_to_doc(a: Assessment) -> Doc:
    return {
        "assessmentId": a.assessment_id,
        "studentId": a.student_id,
        "submissionId": a.submission_id,
        "sessionId": a.session_id,
        "runId": a.run_id,
        "status": a.status.value,
        "questionId": a.question_id,
        "questionVersion": a.question_version,
        "rubricId": a.rubric_id,
        "rubricVersion": a.rubric_version,
        "rubricResults": [
            {
                "criterionId": r.criterion_id,
                "earned": r.earned,
                "possible": r.possible,
                "evidenceRefs": list(r.evidence_refs),
                "assessable": r.assessable,
            }
            for r in a.rubric_results
        ],
        "hintUsage": {
            "serverHintCount": a.hint_usage.server_hint_count,
            "selfReportedHelp": a.hint_usage.self_reported_help,
        },
        "skillEvidence": [
            {"skillId": e.skill_id, "observation": e.observation.value} for e in a.skill_evidence
        ],
        "uncertainty": {"level": a.uncertainty.level.value, "reasons": list(a.uncertainty.reasons)},
        "provenance": {
            "modelVersion": a.provenance.model_version,
            "workflowVersion": a.provenance.workflow_version,
            "toolResultIds": list(a.provenance.tool_result_ids),
        },
        "supersedesAssessmentId": a.supersedes_assessment_id,
        "feedback": a.feedback,
        "createdAt": a.created_at,
    }


def assessment_from_doc(d: Doc) -> Assessment:
    hu, un, pv = d["hintUsage"], d["uncertainty"], d["provenance"]
    return Assessment(
        assessment_id=d["assessmentId"],
        student_id=d["studentId"],
        submission_id=d["submissionId"],
        session_id=d["sessionId"],
        run_id=d["runId"],
        status=AssessmentStatus(d["status"]),
        question_id=d.get("questionId"),
        question_version=d["questionVersion"],
        rubric_id=d.get("rubricId"),
        rubric_version=d["rubricVersion"],
        rubric_results=tuple(
            RubricResult(
                criterion_id=r["criterionId"],
                earned=int(r["earned"]),
                possible=int(r["possible"]),
                evidence_refs=tuple(r.get("evidenceRefs", [])),
                assessable=bool(r.get("assessable", True)),
            )
            for r in d["rubricResults"]
        ),
        hint_usage=HintUsage(
            server_hint_count=int(hu["serverHintCount"]),
            self_reported_help=bool(hu.get("selfReportedHelp", False)),
        ),
        skill_evidence=tuple(
            SkillEvidence(skill_id=e["skillId"], observation=EvidenceObservation(e["observation"]))
            for e in d["skillEvidence"]
        ),
        uncertainty=Uncertainty(
            level=UncertaintyLevel(un["level"]), reasons=tuple(un.get("reasons", []))
        ),
        provenance=Provenance(
            model_version=pv["modelVersion"],
            workflow_version=pv["workflowVersion"],
            tool_result_ids=tuple(pv.get("toolResultIds", [])),
        ),
        supersedes_assessment_id=d.get("supersedesAssessmentId"),
        feedback=d.get("feedback", ""),
        created_at=d.get("createdAt"),
    )


class FirestoreAssessmentStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext, assessment_id: str) -> Assessment | None:
        doc = await self._txn.get(paths.sub(actor, "assessments", assessment_id))
        return assessment_from_doc(doc) if doc else None

    async def list_for_session(
        self, actor: ActorContext, session_id: str, page: PageRequest
    ) -> PaginatedResponse[Assessment]:
        return await paged_query(
            self._txn,
            paths.sub(actor, "assessments"),
            filters=[Filter("sessionId", "==", session_id)],
            order_by=("createdAt", "assessmentId"),
            page=page,
            decode=assessment_from_doc,
        )

    def create(self, actor: ActorContext, a: Assessment) -> None:
        if a.student_id != actor.student_id:
            raise ValueError("assessment does not belong to actor")
        self._txn.set(paths.sub(actor, "assessments", a.assessment_id), assessment_to_doc(a))


def _contribution(d: dict[str, Any]) -> MasteryContribution:
    return MasteryContribution(
        assessment_id=d["assessmentId"],
        question_id=d["questionId"],
        observation=EvidenceObservation(d["observation"]),
        recorded_at=d["recordedAt"],
    )


class FirestoreMasteryStore:
    """`students/{id}/mastery/{skillId}`; the Twin summary reads level + independent count."""

    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext, skill_id: str) -> MasteryState | None:
        d = await self._txn.get(paths.sub(actor, "mastery", skill_id))
        if d is None:
            return None
        return MasteryState(
            skill_id=d["skillId"],
            course_id=d["courseId"],
            level=MasteryLevel(d["level"]),
            independent_evidence_count=int(d.get("independentEvidenceCount", 0)),
            evidence_count=int(d.get("evidenceCount", 0)),
            coverage=int(d.get("coverage", 0)),
            uncertainty=UncertaintyLevel(d.get("uncertainty", "high")),
            updated_at=d.get("updatedAt"),
            # Stored as a list: application ids contain "." (skill ids), which Firestore
            # would treat as a field path inside a map key.
            contributions={
                c["applicationId"]: _contribution(c) for c in d.get("contributions", [])
            },
            rule_version=d.get("ruleVersion", ""),
        )

    def save(self, actor: ActorContext, m: MasteryState) -> None:
        self._txn.set(
            paths.sub(actor, "mastery", m.skill_id),
            {
                "skillId": m.skill_id,
                "courseId": m.course_id,
                "level": m.level.value,
                "independentEvidenceCount": m.independent_evidence_count,
                "evidenceCount": m.evidence_count,
                "coverage": m.coverage,
                "uncertainty": m.uncertainty.value,
                "updatedAt": m.updated_at,
                "ruleVersion": m.rule_version,
                "contributions": [
                    {
                        "applicationId": k,
                        "assessmentId": c.assessment_id,
                        "questionId": c.question_id,
                        "observation": c.observation.value,
                        "recordedAt": c.recorded_at,
                    }
                    for k, c in sorted(m.contributions.items())
                ],
            },
        )
