"""Firestore document layout (BACKEND.md §3). Every learning path is under one student."""

from __future__ import annotations

from app.domain.types.actor import ActorContext


def student(actor_or_id: ActorContext | str) -> str:
    sid = actor_or_id if isinstance(actor_or_id, str) else actor_or_id.student_id
    if not sid or "/" in sid:
        raise ValueError("invalid student id")
    return f"students/{sid}"


def sub(actor: ActorContext, collection: str, doc_id: str | None = None) -> str:
    base = f"{student(actor)}/{collection}"
    if doc_id is None:
        return base
    if not doc_id or "/" in doc_id:
        raise ValueError("invalid document id")
    return f"{base}/{doc_id}"


def identity(uid: str) -> str:
    if not uid or "/" in uid:
        raise ValueError("invalid uid")
    return f"identities/{uid}"
