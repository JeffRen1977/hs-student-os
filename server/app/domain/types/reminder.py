"""Opt-in study reminders (Step 29, BACKEND.md §8).

A reminder is a once-per-local-day digest ("You have 2 study tasks planned today") on the
one channel the student opted into. Its id is the delivery dedupe key
`{localDate}.{channel}`: one per student, channel and local day, however many times
planning runs. What it says is decided when it is sent, from the tasks as they are then.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from app.domain.types.student import NotificationChannel

CONSENT_POLICY_VERSION = "reminders-v1"


class ReminderStatus(StrEnum):
    PENDING = "pending"  # waiting for sendAt
    SENDING = "sending"  # claimed by a delivery attempt (claimedAt = lease start)
    SENT = "sent"
    SKIPPED = "skipped"  # never sent; see skip_reason


class ReminderSkipReason(StrEnum):
    CONSENT_REVOKED = "consent_revoked"  # opted out after the reminder was created
    NOTHING_PLANNED = "nothing_planned"  # every task for the day is done, skipped or moved
    FREQUENCY_CAP = "frequency_cap"
    QUIET_HOURS = "quiet_hours"  # quiet hours last until the day is over
    EXPIRED = "expired"  # the local day passed before delivery (e.g. downtime)
    NOT_TEST_RECIPIENT = "not_test_recipient"  # real delivery is limited to test recipients
    DELIVERY_FAILED = "delivery_failed"  # retries exhausted


@dataclass(frozen=True, slots=True, kw_only=True)
class Reminder:
    reminder_id: str  # == dedupe key: f"{local_date}.{channel}"
    student_id: str
    channel: NotificationChannel
    local_date: date
    send_at: datetime
    status: ReminderStatus
    created_at: datetime
    updated_at: datetime
    skip_reason: ReminderSkipReason | None = None
    attempts: int = 0
    claimed_at: datetime | None = None
    sent_at: datetime | None = None
    version: int = 1

    @staticmethod
    def make_id(day: date, channel: NotificationChannel) -> str:
        return f"{day.isoformat()}.{channel.value}"


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationConsent:
    """`students/{id}/consents/notifications`: the record of the student's opt-in.

    Written only by the twin patch that changes `preferences.notifications`; delivery
    checks it again immediately before every send.
    """

    granted: bool
    channels: Sequence[NotificationChannel]
    policy_version: str
    granted_at: datetime | None
    revoked_at: datetime | None
    updated_at: datetime

    def allows(self, channel: NotificationChannel) -> bool:
        return self.granted and channel in self.channels


@dataclass(frozen=True, slots=True, kw_only=True)
class ReminderMessage:
    """What a sender delivers. Recipient is always the student themself (no parent or
    other recipient exists in the pilot). Never logged: it is student-facing text."""

    dedupe_key: str  # f"{student_id}/{reminder_id}": providers dedupe on it
    student_id: str
    channel: NotificationChannel
    title: str
    body: str
