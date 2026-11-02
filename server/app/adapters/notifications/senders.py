"""Reminder senders (Step 29.3).

No real channel provider is wired in the pilot yet. `FakeReminderSender` records messages
in memory and dedupes on the message's key, like a real provider's idempotency key; it is
used by tests and local development. `TestRecipientGuard` wraps any sender so that only
designated synthetic test students can receive anything: every other recipient comes back
NOT_ALLOWED and the reminder is skipped. Deployed environments must use the guard until
the pilot gate (Step 33) allows real recipients.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from app.domain.ports.notifications import DeliveryOutcome, ReminderDeliveryError, ReminderSender
from app.domain.types.reminder import ReminderMessage

logger = logging.getLogger(__name__)


class FakeReminderSender:
    def __init__(self) -> None:
        self.delivered: dict[str, ReminderMessage] = {}
        self.attempts = 0
        self.fail_next = 0  # fault injection: raise on the next N sends

    async def send(self, message: ReminderMessage) -> DeliveryOutcome:
        self.attempts += 1
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ReminderDeliveryError("injected delivery failure")
        if message.dedupe_key in self.delivered:
            return DeliveryOutcome.ALREADY_DELIVERED
        self.delivered[message.dedupe_key] = message
        # Ids and channel only: the message text is student-facing content.
        logger.info(
            "reminder_delivered_fake",
            extra={"studentId": message.student_id, "channel": message.channel.value},
        )
        return DeliveryOutcome.DELIVERED


class TestRecipientGuard:
    __test__ = False  # not a pytest class

    def __init__(self, inner: ReminderSender, allowed_student_ids: Iterable[str]) -> None:
        self._inner = inner
        self._allowed = frozenset(allowed_student_ids)

    async def send(self, message: ReminderMessage) -> DeliveryOutcome:
        if message.student_id not in self._allowed:
            return DeliveryOutcome.NOT_ALLOWED
        return await self._inner.send(message)
