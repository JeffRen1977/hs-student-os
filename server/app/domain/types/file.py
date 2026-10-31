from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FileStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredFile:
    """File metadata only; bytes live in object storage (upload flow lands in Step 21)."""

    file_id: str
    student_id: str
    status: FileStatus
