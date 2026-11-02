"""Opt-in study reminders (Step 29.2, BACKEND.md §8).

Lifecycle of one reminder (`students/{id}/reminders/{localDate}.{channel}`):

1. **Consent.** A twin patch that changes `preferences.notifications` writes the consent
   record (`record_notification_consent`). Reminders are off by default; the pilot allows
   one channel; nobody but the student is ever a recipient (no parent notifications).
2. **Create.** When a plan is committed (scheduled or student replan), `sync_in_tx` creates
   today's reminder if the student has consented and has open tasks today. The reminder
   time (16:00 local by default) is moved out of quiet hours; if quiet hours last until
   the day is over, no reminder is created. The id is the dedupe key, so replanning never
   creates a second one.
3. **Claim.** The delivery scan (`deliver_due`, Cloud Scheduler) claims a due reminder in a
   transaction that re-checks everything immediately before sending: consent and
   preference still on, still the same local day, not in quiet hours (else deferred to the
   end of quiet hours), at least one open task still scheduled for that day (completed,
   skipped or moved tasks drop out), and the weekly frequency cap.
4. **Send** outside any transaction with the dedupe key. A crash after sending leaves the
   claim to expire; the retry sends the same key and the provider reports it as already
   delivered, so the student gets one message.
5. **Finish**: sent, retried later, or skipped with a reason.
"""

from __future__ import annotations

import dataclasses
import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.domain.local_time import at_local, in_window, local_date, parse_hhmm, window_end
from app.domain.ports.metrics import Metrics, NullMetrics
from app.domain.ports.notifications import DeliveryOutcome, ReminderSender
from app.domain.ports.repositories import OperationsStore, TaskQuery, Tx, UnitOfWork
from app.domain.ports.runtime import Clock
from app.domain.types.actor import ActorContext
from app.domain.types.common import PageRequest
from app.domain.types.course import EnrollmentStatus
from app.domain.types.reminder import (
    CONSENT_POLICY_VERSION,
    NotificationConsent,
    Reminder,
    ReminderMessage,
    ReminderSkipReason,
    ReminderStatus,
)
from app.domain.types.student import NotificationChannel, NotificationPreferences, Student
from app.domain.types.task import Task, TaskStatus

logger = logging.getLogger(__name__)

REMINDER_SERVICE = "reminders"
OPEN_STATUSES = frozenset({TaskStatus.PLANNED, TaskStatus.IN_PROGRESS})


@dataclass(frozen=True, slots=True, kw_only=True)
class ReminderPolicy:
    enabled: bool = False  # platform switch: off unless a sender is configured
    local_time: time = time(16, 0)
    weekly_cap: int = 5  # sent reminders per student in any 7 local days
    claim_seconds: int = 300  # a claimed delivery attempt older than this is retried
    max_attempts: int = 3
    retry_seconds: int = 300


# ---- Consent (called from the twin patch transaction) ---------------------------------


async def record_notification_consent(
    tx: Tx,
    actor: ActorContext,
    after: NotificationPreferences,
    now: datetime,
) -> None:
    existing = await tx.consents.get_notifications(actor)
    wants = after.enabled and bool(after.channels)
    if wants:
        if existing and existing.granted and tuple(existing.channels) == tuple(after.channels):
            return
        tx.consents.save_notifications(
            actor,
            NotificationConsent(
                granted=True,
                channels=tuple(after.channels),
                policy_version=CONSENT_POLICY_VERSION,
                granted_at=now,
                revoked_at=None,
                updated_at=now,
            ),
        )
    elif existing is not None and existing.granted:
        tx.consents.save_notifications(
            actor,
            dataclasses.replace(
                existing, granted=False, channels=(), revoked_at=now, updated_at=now
            ),
        )


def _allowed(
    student: Student, consent: NotificationConsent | None, channel: NotificationChannel
) -> bool:
    prefs = student.preferences.notifications
    return (
        prefs.enabled
        and channel in prefs.channels
        and consent is not None
        and consent.allows(channel)
    )


class ReminderService:
    def __init__(
        self,
        uow: UnitOfWork,
        operations: OperationsStore,
        sender: ReminderSender | None,
        clock: Clock,
        policy: ReminderPolicy,
        metrics: Metrics | None = None,
    ) -> None:
        self._metrics: Metrics = metrics or NullMetrics()
        self._uow = uow
        self._ops = operations
        self._sender = sender
        self._clock = clock
        self._policy = policy

    @property
    def enabled(self) -> bool:
        return self._policy.enabled and self._sender is not None

    # ---- Create (inside the plan commit transaction) ----------------------------------

    def _send_time(self, student: Student, day: date, now: datetime) -> datetime | None:
        tz = student.preferences.timezone
        send_at = max(now, at_local(day, self._policy.local_time, tz))
        quiet = student.preferences.notifications.quiet_hours
        if quiet is not None:
            start, end = parse_hhmm(quiet.start), parse_hhmm(quiet.end)
            if in_window(send_at, start, end, tz):
                send_at = window_end(send_at, start, end, tz)
        return send_at if local_date(send_at, tz) == day else None

    async def sync_in_tx(
        self,
        tx: Tx,
        actor: ActorContext,
        student: Student,
        day: date,
        tasks_today: Sequence[Task],
        now: datetime,
    ) -> None:
        if not self.enabled or not any(t.status in OPEN_STATUSES for t in tasks_today):
            return
        consent = await tx.consents.get_notifications(actor)
        for channel in student.preferences.notifications.channels:
            if not _allowed(student, consent, channel):
                continue
            reminder_id = Reminder.make_id(day, channel)
            if await tx.reminders.get(actor, reminder_id) is not None:
                continue  # dedupe: one per student, channel and local day
            send_at = self._send_time(student, day, now)
            if send_at is None:
                continue
            tx.reminders.save(
                actor,
                Reminder(
                    reminder_id=reminder_id,
                    student_id=actor.student_id,
                    channel=channel,
                    local_date=day,
                    send_at=send_at,
                    status=ReminderStatus.PENDING,
                    created_at=now,
                    updated_at=now,
                ),
            )

    # ---- Deliver (Cloud Scheduler scan) -----------------------------------------------

    async def deliver_due(self, limit: int = 100) -> Counter[str]:
        results: Counter[str] = Counter()
        if self._sender is None:
            return results
        now = self._clock.now()
        due = await self._ops.due_reminders(
            due_before=now,
            claim_expired_before=now - timedelta(seconds=self._policy.claim_seconds),
            limit=limit,
        )
        for student_id, reminder_id in due:
            actor = ActorContext.for_service(REMINDER_SERVICE, student_id)
            try:
                results[await self._deliver_one(actor, reminder_id)] += 1
            except Exception as exc:  # isolate students; the claim lease brings it back
                logger.warning(
                    "reminder_delivery_error",
                    extra={"studentId": student_id, "error": type(exc).__name__},
                )
                results["error"] += 1
        for outcome, n in results.items():
            self._metrics.count("reminder.outcome", n, outcome=outcome)
            if outcome == "deduplicated":
                self._metrics.count("duplicate.suppressed", n, source="reminder")
        if results:
            logger.info("reminder_scan", extra=dict(results))
        return results

    async def _deliver_one(self, actor: ActorContext, reminder_id: str) -> str:
        assert self._sender is not None
        claim = await self._uow.transaction(lambda tx: self._claim(tx, actor, reminder_id))
        if isinstance(claim, str):
            return claim
        message, claimed_at = claim
        try:
            outcome: DeliveryOutcome | None = await self._sender.send(message)
        except Exception as exc:  # any provider failure is retried with the same key
            logger.warning(
                "reminder_send_failed",
                extra={"studentId": actor.student_id, "error": type(exc).__name__},
            )
            outcome = None

        async def finish(tx: Tx) -> str:
            return await self._finish(tx, actor, reminder_id, claimed_at, outcome)

        return await self._uow.transaction(finish)

    def _skip(self, r: Reminder, reason: ReminderSkipReason, now: datetime) -> Reminder:
        return dataclasses.replace(
            r,
            status=ReminderStatus.SKIPPED,
            skip_reason=reason,
            claimed_at=None,
            updated_at=now,
            version=r.version + 1,
        )

    async def _claim(
        self, tx: Tx, actor: ActorContext, reminder_id: str
    ) -> tuple[ReminderMessage, datetime] | str:
        now = self._clock.now()
        r = await tx.reminders.get(actor, reminder_id)
        if r is None or r.status in (ReminderStatus.SENT, ReminderStatus.SKIPPED):
            return "obsolete"
        if r.status is ReminderStatus.PENDING and r.send_at > now:
            return "not_due"
        lease = timedelta(seconds=self._policy.claim_seconds)
        if (
            r.status is ReminderStatus.SENDING
            and r.claimed_at is not None
            and r.claimed_at > now - lease
        ):
            return "in_flight"
        student = await tx.students.get(actor)
        consent = await tx.consents.get_notifications(actor)
        if student is None or not _allowed(student, consent, r.channel):
            tx.reminders.save(actor, self._skip(r, ReminderSkipReason.CONSENT_REVOKED, now))
            return ReminderSkipReason.CONSENT_REVOKED.value
        tz = student.preferences.timezone
        if local_date(now, tz) != r.local_date:
            tx.reminders.save(actor, self._skip(r, ReminderSkipReason.EXPIRED, now))
            return ReminderSkipReason.EXPIRED.value
        quiet = student.preferences.notifications.quiet_hours
        if quiet is not None:
            start, end = parse_hhmm(quiet.start), parse_hhmm(quiet.end)
            if in_window(now, start, end, tz):
                later = window_end(now, start, end, tz)
                if local_date(later, tz) != r.local_date:
                    tx.reminders.save(actor, self._skip(r, ReminderSkipReason.QUIET_HOURS, now))
                    return ReminderSkipReason.QUIET_HOURS.value
                tx.reminders.save(
                    actor,
                    dataclasses.replace(
                        r,
                        status=ReminderStatus.PENDING,
                        send_at=later,
                        claimed_at=None,
                        updated_at=now,
                        version=r.version + 1,
                    ),
                )
                return "deferred"
        open_tasks = await self._open_tasks(tx, actor, r.local_date)
        if not open_tasks:
            tx.reminders.save(actor, self._skip(r, ReminderSkipReason.NOTHING_PLANNED, now))
            return ReminderSkipReason.NOTHING_PLANNED.value
        recent = await tx.reminders.list_since(actor, r.local_date - timedelta(days=6))
        sent = [
            x for x in recent if x.status is ReminderStatus.SENT and x.reminder_id != r.reminder_id
        ]
        if len(sent) >= self._policy.weekly_cap:
            tx.reminders.save(actor, self._skip(r, ReminderSkipReason.FREQUENCY_CAP, now))
            return ReminderSkipReason.FREQUENCY_CAP.value
        tx.reminders.save(
            actor,
            dataclasses.replace(
                r,
                status=ReminderStatus.SENDING,
                attempts=r.attempts + 1,
                claimed_at=now,
                updated_at=now,
                version=r.version + 1,
            ),
        )
        minutes = sum(t.duration_min for t in open_tasks)
        count = len(open_tasks)
        noun = "task" if count == 1 else "tasks"
        message = ReminderMessage(
            dedupe_key=f"{actor.student_id}/{r.reminder_id}",
            student_id=actor.student_id,
            channel=r.channel,
            title="Today's study plan",
            body=f"You have {count} study {noun} planned today ({minutes} min).",
        )
        return message, now

    async def _open_tasks(self, tx: Tx, actor: ActorContext, day: date) -> list[Task]:
        enrolled = sorted(
            e.course_id for e in await tx.enrollments.list(actor, status=EnrollmentStatus.ACTIVE)
        )
        page = await tx.tasks.list(
            actor, TaskQuery(scheduled_date=day, course_ids=enrolled), PageRequest(limit=100)
        )
        return [t for t in page.items if t.status in OPEN_STATUSES]

    async def _finish(
        self,
        tx: Tx,
        actor: ActorContext,
        reminder_id: str,
        claimed_at: datetime,
        outcome: DeliveryOutcome | None,
    ) -> str:
        now = self._clock.now()
        r = await tx.reminders.get(actor, reminder_id)
        if r is None or r.status is not ReminderStatus.SENDING or r.claimed_at != claimed_at:
            return "superseded"  # another attempt took over after our claim expired
        if outcome in (DeliveryOutcome.DELIVERED, DeliveryOutcome.ALREADY_DELIVERED):
            tx.reminders.save(
                actor,
                dataclasses.replace(
                    r,
                    status=ReminderStatus.SENT,
                    sent_at=now,
                    claimed_at=None,
                    updated_at=now,
                    version=r.version + 1,
                ),
            )
            return "sent" if outcome is DeliveryOutcome.DELIVERED else "deduplicated"
        if outcome is DeliveryOutcome.NOT_ALLOWED:
            tx.reminders.save(actor, self._skip(r, ReminderSkipReason.NOT_TEST_RECIPIENT, now))
            return ReminderSkipReason.NOT_TEST_RECIPIENT.value
        if r.attempts >= self._policy.max_attempts:
            tx.reminders.save(actor, self._skip(r, ReminderSkipReason.DELIVERY_FAILED, now))
            return ReminderSkipReason.DELIVERY_FAILED.value
        tx.reminders.save(
            actor,
            dataclasses.replace(
                r,
                status=ReminderStatus.PENDING,
                send_at=now + timedelta(seconds=self._policy.retry_seconds),
                claimed_at=None,
                updated_at=now,
                version=r.version + 1,
            ),
        )
        return "retry"
