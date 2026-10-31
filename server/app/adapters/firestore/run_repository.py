from __future__ import annotations

from app.adapters.firestore import paths
from app.adapters.firestore.documents import Doc, DocTxn
from app.domain.types.actor import ActorContext
from app.domain.types.outbox import RunInput
from app.domain.types.run import (
    InputRequest,
    InputRequestKind,
    Run,
    RunError,
    RunKind,
    RunResult,
    RunStatus,
)


def run_to_doc(r: Run) -> Doc:
    return {
        "runId": r.run_id,
        "studentId": r.student_id,
        "sessionId": r.session_id,
        "status": r.status.value,
        "kind": r.kind.value,
        "submissionId": r.submission_id,
        "messageId": r.message_id,
        "attemptCount": r.attempt_count,
        "inputRequest": (
            {
                "inputRequestId": r.input_request.input_request_id,
                "kind": r.input_request.kind.value,
                "prompt": r.input_request.prompt,
            }
            if r.input_request
            else None
        ),
        "result": (
            {
                "messageId": r.result.message_id,
                "assessmentId": r.result.assessment_id,
                "planId": r.result.plan_id,
            }
            if r.result
            else None
        ),
        "error": {"code": r.error.code, "retryable": r.error.retryable} if r.error else None,
        "cancelRequested": r.cancel_requested,
        "leaseFencingToken": r.lease_fencing_token,
        "leaseOwner": r.lease_owner,
        "leaseExpiresAt": r.lease_expires_at,
        "dispatchGeneration": r.dispatch_generation,
        "createdAt": r.created_at,
        "updatedAt": r.updated_at,
    }


def run_from_doc(d: Doc) -> Run:
    ir, res, err = d.get("inputRequest"), d.get("result"), d.get("error")
    return Run(
        run_id=d["runId"],
        student_id=d["studentId"],
        session_id=d.get("sessionId"),
        status=RunStatus(d["status"]),
        kind=RunKind(d["kind"]),
        submission_id=d.get("submissionId"),
        message_id=d.get("messageId"),
        attempt_count=int(d.get("attemptCount", 0)),
        input_request=(
            InputRequest(
                input_request_id=ir["inputRequestId"],
                kind=InputRequestKind(ir["kind"]),
                prompt=ir["prompt"],
            )
            if ir
            else None
        ),
        result=(
            RunResult(
                message_id=res.get("messageId"),
                assessment_id=res.get("assessmentId"),
                plan_id=res.get("planId"),
            )
            if res
            else None
        ),
        error=RunError(code=err["code"], retryable=bool(err["retryable"])) if err else None,
        cancel_requested=bool(d.get("cancelRequested", False)),
        lease_fencing_token=int(d.get("leaseFencingToken", 0)),
        lease_owner=d.get("leaseOwner"),
        lease_expires_at=d.get("leaseExpiresAt"),
        dispatch_generation=int(d.get("dispatchGeneration", 1)),
        created_at=d.get("createdAt"),
        updated_at=d.get("updatedAt"),
    )


class FirestoreRunStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext, run_id: str) -> Run | None:
        doc = await self._txn.get(paths.sub(actor, "runs", run_id))
        return run_from_doc(doc) if doc else None

    def save(self, actor: ActorContext, run: Run) -> None:
        if run.student_id != actor.student_id:
            raise ValueError("run does not belong to actor")
        self._txn.set(paths.sub(actor, "runs", run.run_id), run_to_doc(run))


class FirestoreRunInputStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    def create(self, actor: ActorContext, run_input: RunInput) -> None:
        if run_input.student_id != actor.student_id:
            raise ValueError("input does not belong to actor")
        self._txn.set(
            paths.sub(actor, "runInputs", run_input.input_request_id),
            {
                "inputRequestId": run_input.input_request_id,
                "runId": run_input.run_id,
                "confirmedText": run_input.confirmed_text,
                "createdAt": run_input.created_at,
            },
        )
