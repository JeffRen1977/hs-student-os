from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from enum import StrEnum

from app.domain.errors import DomainError, ErrorCode


class FileStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True, kw_only=True)
class StoredFile:
    """File metadata. Image bytes for photo answers are kept beside it (see FileStore)."""

    file_id: str
    student_id: str
    status: FileStatus
    media_type: str = ""
    size_bytes: int = 0


# Photo answers (handwritten work). The browser downscales before upload; the cap keeps a
# file inside one document (Firestore's limit is 1 MiB) until Cloud Storage uploads exist.
IMAGE_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_IMAGE_BYTES = 600_000


@dataclass(frozen=True, slots=True, kw_only=True)
class ImageContent:
    media_type: str
    data_base64: str


def _matches(media_type: str, data: bytes) -> bool:
    if media_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if media_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def validate_image(media_type: str, data_base64: str) -> int:
    """Decoded size of a valid photo; rejects other types, bad encoding, size and spoofing."""
    if media_type not in IMAGE_MEDIA_TYPES:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Photos must be JPEG, PNG or WebP.")
    try:
        data = base64.b64decode(data_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Photo data is not valid base64.") from exc
    if not data:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Photo is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Photo is too large (max 600 KB).")
    if not _matches(media_type, data):
        raise DomainError(ErrorCode.VALIDATION_FAILED, "Photo content does not match its type.")
    return len(data)
