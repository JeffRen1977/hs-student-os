"""Course access administration (Step 42): the access record and its audit trail."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.types.student import Entitlements


class AccessChange(StrEnum):
    GRANT = "grant"
    REVOKE = "revoke"


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessRecord:
    """`students/{id}/access/current`: the grants plus who last changed them."""

    entitlements: Entitlements
    updated_at: datetime | None = None
    updated_by: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AccessAuditEntry:
    """One grant or revoke, written in the same transaction as the access record.
    Readable by platform admins only; the student sees a filtered `access.changed`."""

    audit_id: str
    student_id: str
    course_id: str
    change: AccessChange
    reason: str
    actor_id: str
    at: datetime
