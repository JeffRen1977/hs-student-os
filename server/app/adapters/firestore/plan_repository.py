"""`students/{id}/plans/{planId}` and `students/{id}/planState/current` (Step 25)."""

from __future__ import annotations

from datetime import date

from app.adapters.firestore import paths
from app.adapters.firestore.documents import Doc, DocTxn
from app.domain.types.actor import ActorContext
from app.domain.types.plan import (
    Placement,
    Plan,
    PlanEntry,
    PlanPriority,
    PlanState,
    PlanTrigger,
)


def _entry_to_doc(e: PlanEntry) -> Doc:
    return {
        "taskId": e.task_id,
        "courseId": e.course_id,
        "durationMin": e.duration_min,
        "previousDate": e.previous_date.isoformat(),
        "scheduledDate": e.scheduled_date.isoformat(),
        "priority": e.priority.value if e.priority else None,
        "placement": e.placement.value,
        "explanation": e.explanation,
        "sourceEventIds": list(e.source_event_ids),
    }


def _entry_from_doc(d: Doc) -> PlanEntry:
    return PlanEntry(
        task_id=d["taskId"],
        course_id=d["courseId"],
        duration_min=int(d["durationMin"]),
        previous_date=date.fromisoformat(d["previousDate"]),
        scheduled_date=date.fromisoformat(d["scheduledDate"]),
        priority=PlanPriority(d["priority"]) if d.get("priority") else None,
        placement=Placement(d["placement"]),
        explanation=d["explanation"],
        source_event_ids=tuple(d.get("sourceEventIds", [])),
    )


class FirestorePlanStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext, plan_id: str) -> Plan | None:
        d = await self._txn.get(paths.sub(actor, "plans", plan_id))
        if d is None:
            return None
        return Plan(
            plan_id=d["planId"],
            student_id=d["studentId"],
            run_id=d.get("runId"),
            rule_version=d["ruleVersion"],
            local_date=date.fromisoformat(d["localDate"]),
            horizon_end=date.fromisoformat(d["horizonEnd"]),
            weekly_minutes=int(d["weeklyMinutes"]),
            daily_minutes=int(d["dailyMinutes"]),
            evidence_available=bool(d["evidenceAvailable"]),
            entries=tuple(_entry_from_doc(e) for e in d.get("entries", [])),
            created_at=d["createdAt"],
            trigger=PlanTrigger(d.get("trigger", PlanTrigger.STUDENT.value)),
        )

    def save(self, actor: ActorContext, p: Plan) -> None:
        if p.student_id != actor.student_id:
            raise ValueError("plan does not belong to actor")
        self._txn.set(
            paths.sub(actor, "plans", p.plan_id),
            {
                "planId": p.plan_id,
                "studentId": p.student_id,
                "runId": p.run_id,
                "ruleVersion": p.rule_version,
                "localDate": p.local_date.isoformat(),
                "horizonEnd": p.horizon_end.isoformat(),
                "weeklyMinutes": p.weekly_minutes,
                "dailyMinutes": p.daily_minutes,
                "evidenceAvailable": p.evidence_available,
                "entries": [_entry_to_doc(e) for e in p.entries],
                "createdAt": p.created_at,
                "trigger": p.trigger.value,
            },
        )

    async def get_state(self, actor: ActorContext) -> PlanState:
        d = await self._txn.get(paths.sub(actor, "planState", "current"))
        if d is None:
            return PlanState()
        last = d.get("lastScheduledLocalDate")
        trigger = d.get("activeTrigger")
        return PlanState(
            active_run_id=d.get("activeRunId"),
            active_trigger=PlanTrigger(trigger) if trigger else None,
            latest_plan_id=d.get("latestPlanId"),
            next_due_at=d.get("nextDueAt"),
            timezone=d.get("timezone"),
            last_scheduled_local_date=date.fromisoformat(last) if last else None,
            version=int(d.get("version", 0)),
        )

    def save_state(self, actor: ActorContext, s: PlanState) -> None:
        self._txn.set(
            paths.sub(actor, "planState", "current"),
            {
                # studentId + nextDueAt make the collection-group scan for due schedules
                # possible (FirestoreOperationsStore.due_plan_schedules).
                "studentId": actor.student_id,
                "activeRunId": s.active_run_id,
                "activeTrigger": s.active_trigger.value if s.active_trigger else None,
                "latestPlanId": s.latest_plan_id,
                "nextDueAt": s.next_due_at,
                "timezone": s.timezone,
                "lastScheduledLocalDate": (
                    s.last_scheduled_local_date.isoformat() if s.last_scheduled_local_date else None
                ),
                "version": s.version,
            },
        )
