from __future__ import annotations

from datetime import datetime
from typing import Any

from app.adapters.firestore import paths
from app.adapters.firestore.documents import Doc, DocTxn, QuerySpec
from app.domain.types.actor import ActorContext
from app.domain.types.student import (
    Entitlements,
    Goals,
    MasteryLevel,
    MasterySummary,
    NotificationChannel,
    NotificationPreferences,
    PredictionStatus,
    PredictionSummary,
    Preferences,
    Profile,
    QuietHours,
    Student,
)

MASTERY_SUMMARY_LIMIT = 500


def profile_to_doc(p: Profile) -> Doc:
    return {
        "displayName": p.display_name,
        "grade": p.grade,
        "school": p.school,
        "targetMajor": p.target_major,
        "targetSchools": list(p.target_schools),
    }


def goals_to_doc(g: Goals) -> Doc:
    return {"satTarget": g.sat_target, "apTargets": dict(g.ap_targets)}


def notifications_to_doc(n: NotificationPreferences) -> Doc:
    return {
        "enabled": n.enabled,
        "channels": [c.value for c in n.channels],
        "quietHours": (
            {"start": n.quiet_hours.start, "end": n.quiet_hours.end} if n.quiet_hours else None
        ),
    }


def preferences_to_doc(p: Preferences) -> Doc:
    return {
        "timezone": p.timezone,
        "weeklyAvailableMinutes": p.weekly_available_minutes,
        "selectedCourses": list(p.selected_courses),
        "notifications": notifications_to_doc(p.notifications),
    }


def _notifications(d: dict[str, Any] | None) -> NotificationPreferences:
    d = d or {}
    qh = d.get("quietHours")
    return NotificationPreferences(
        enabled=bool(d.get("enabled", False)),
        channels=tuple(NotificationChannel(c) for c in d.get("channels", [])),
        quiet_hours=QuietHours(start=qh["start"], end=qh["end"]) if qh else None,
    )


def student_from_doc(doc: Doc, mastery: dict[str, MasterySummary], latest_sequence: int) -> Student:
    p, g, pr = doc["profile"], doc.get("goals", {}), doc["preferences"]
    return Student(
        student_id=doc["studentId"],
        version=int(doc["version"]),
        profile=Profile(
            display_name=p["displayName"],
            grade=int(p["grade"]),
            school=p.get("school"),
            target_major=p.get("targetMajor"),
            target_schools=tuple(p.get("targetSchools", [])),
        ),
        goals=Goals(sat_target=g.get("satTarget"), ap_targets=dict(g.get("apTargets", {}))),
        preferences=Preferences(
            timezone=pr["timezone"],
            weekly_available_minutes=int(pr["weeklyAvailableMinutes"]),
            selected_courses=tuple(pr.get("selectedCourses", [])),
            notifications=_notifications(pr.get("notifications")),
        ),
        mastery_summary=mastery,
        prediction_summary={
            # Only "unavailable" exists until calibrated predictions ship (CLAUDE.md §1.3).
            cid: PredictionSummary(
                status=PredictionStatus(v.get("status", "unavailable")),
                reason=v.get("reason", "not_calibrated"),
            )
            for cid, v in doc.get("predictionSummary", {}).items()
        },
        latest_event_sequence=latest_sequence,
    )


class FirestoreStudentStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext) -> Student | None:
        doc = await self._txn.get(paths.student(actor))
        if doc is None:
            return None
        mastery_docs = await self._txn.query(
            paths.sub(actor, "mastery"),
            QuerySpec(order_by=("skillId",), limit=MASTERY_SUMMARY_LIMIT),
        )
        mastery = {
            m["skillId"]: MasterySummary(
                level=MasteryLevel(m["level"]),
                independent_evidence_count=int(m.get("independentEvidenceCount", 0)),
            )
            for m in mastery_docs
        }
        state = await self._txn.get(paths.sub(actor, "eventState", "current"))
        latest = int(state["nextSequence"]) - 1 if state else 0
        return student_from_doc(doc, mastery, latest)

    async def get_entitlements(self, actor: ActorContext) -> Entitlements:
        doc = await self._txn.get(paths.sub(actor, "access", "current"))
        if doc is None:
            return Entitlements()
        return Entitlements(
            ap_courses=tuple(doc.get("apCourses", [])),
            dsat=bool(doc.get("dsat", False)),
            admissions=bool(doc.get("admissions", False)),
        )

    def save_twin(self, actor: ActorContext, student: Student, *, now: datetime) -> None:
        if student.student_id != actor.student_id:
            raise ValueError("student does not belong to actor")
        # `update` replaces only these top-level fields; access/, mastery/, etc. live in
        # separate documents and cannot be touched from here.
        self._txn.update(
            paths.student(actor),
            {
                "version": student.version,
                "profile": profile_to_doc(student.profile),
                "goals": goals_to_doc(student.goals),
                "preferences": preferences_to_doc(student.preferences),
                "updatedAt": now,
            },
        )
