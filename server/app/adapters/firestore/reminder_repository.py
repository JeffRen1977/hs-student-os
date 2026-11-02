"""`students/{id}/reminders/{reminderId}` and `students/{id}/consents/notifications`
(Step 29)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from app.adapters.firestore import paths
from app.adapters.firestore.documents import Doc, DocTxn, Filter, QuerySpec
from app.domain.types.actor import ActorContext
from app.domain.types.reminder import (
    NotificationConsent,
    Reminder,
    ReminderSkipReason,
    ReminderStatus,
)
from app.domain.types.student import NotificationChannel


def reminder_to_doc(r: Reminder) -> Doc:
    return {
        "reminderId": r.reminder_id,
        "studentId": r.student_id,
        "channel": r.channel.value,
        "localDate": r.local_date.isoformat(),
        "sendAt": r.send_at,
        "status": r.status.value,
        "skipReason": r.skip_reason.value if r.skip_reason else None,
        "attempts": r.attempts,
        "claimedAt": r.claimed_at,
        "sentAt": r.sent_at,
        "createdAt": r.created_at,
        "updatedAt": r.updated_at,
        "version": r.version,
    }


def reminder_from_doc(d: Doc) -> Reminder:
    return Reminder(
        reminder_id=d["reminderId"],
        student_id=d["studentId"],
        channel=NotificationChannel(d["channel"]),
        local_date=date.fromisoformat(d["localDate"]),
        send_at=d["sendAt"],
        status=ReminderStatus(d["status"]),
        skip_reason=ReminderSkipReason(d["skipReason"]) if d.get("skipReason") else None,
        attempts=int(d.get("attempts", 0)),
        claimed_at=d.get("claimedAt"),
        sent_at=d.get("sentAt"),
        created_at=d["createdAt"],
        updated_at=d["updatedAt"],
        version=int(d.get("version", 1)),
    )


class FirestoreReminderStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, actor: ActorContext, reminder_id: str) -> Reminder | None:
        d = await self._txn.get(paths.sub(actor, "reminders", reminder_id))
        return reminder_from_doc(d) if d else None

    async def list_since(self, actor: ActorContext, since: date) -> Sequence[Reminder]:
        docs = await self._txn.query(
            paths.sub(actor, "reminders"),
            QuerySpec(
                filters=[Filter("localDate", ">=", since.isoformat())],
                order_by=("localDate",),
                limit=100,
            ),
        )
        return [reminder_from_doc(d) for d in docs]

    def save(self, actor: ActorContext, reminder: Reminder) -> None:
        if reminder.student_id != actor.student_id:
            raise ValueError("reminder does not belong to actor")
        self._txn.set(
            paths.sub(actor, "reminders", reminder.reminder_id), reminder_to_doc(reminder)
        )


class FirestoreConsentStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get_notifications(self, actor: ActorContext) -> NotificationConsent | None:
        d = await self._txn.get(paths.sub(actor, "consents", "notifications"))
        if d is None:
            return None
        return NotificationConsent(
            granted=bool(d["granted"]),
            channels=tuple(NotificationChannel(c) for c in d.get("channels", [])),
            policy_version=d["policyVersion"],
            granted_at=d.get("grantedAt"),
            revoked_at=d.get("revokedAt"),
            updated_at=d["updatedAt"],
        )

    def save_notifications(self, actor: ActorContext, c: NotificationConsent) -> None:
        self._txn.set(
            paths.sub(actor, "consents", "notifications"),
            {
                "granted": c.granted,
                "channels": [ch.value for ch in c.channels],
                "policyVersion": c.policy_version,
                "grantedAt": c.granted_at,
                "revokedAt": c.revoked_at,
                "updatedAt": c.updated_at,
            },
        )
