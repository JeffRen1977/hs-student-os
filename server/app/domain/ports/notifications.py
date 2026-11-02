"""Reminder delivery port (Step 29.3). Called only outside transactions."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from app.domain.types.reminder import ReminderMessage


class DeliveryOutcome(StrEnum):
    DELIVERED = "delivered"
    ALREADY_DELIVERED = "already_delivered"  # same dedupe key seen before: not re-sent
    NOT_ALLOWED = "not_allowed"  # recipient is not a designated test recipient


class ReminderDeliveryError(Exception):
    """A failed attempt. Retried with the same dedupe key until attempts run out."""


class ReminderSender(Protocol):
    async def send(self, message: ReminderMessage) -> DeliveryOutcome: ...
