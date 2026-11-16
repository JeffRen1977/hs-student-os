"""Authoring assistant turns and proposals (Step 40, QUESTION_BANK.md §4.5).

A turn is one request to the assistant: the user's message plus a snapshot of what they
selected (items with the revision they had, passages, source pages, course skills). The
assistant answers with a short reply and typed proposals; people accept or reject each one.
Proposals never change anything until accepted, and are applied through the normal bank
and selection commands as the accepting user.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from app.domain.types.bank import ImportLease, ImportStatus


class TurnMode(StrEnum):
    BANK = "bank"  # 40A: questions in the bank
    DESIGN = "design"  # 40B: sets, skill tags and skills for a selection (content reviewer)


class ProposalKind(StrEnum):
    CREATE_ITEM = "create-item"
    EDIT_ITEM = "edit-item"
    PROPOSE_KEY = "propose-key"
    LINK_PASSAGE = "link-passage"
    FLAG = "flag"
    SELECTION_SETS = "selection-sets"  # 40B
    ADD_SKILL = "add-skill"  # 40B


REVIEWER_KINDS = frozenset(
    {ProposalKind.PROPOSE_KEY, ProposalKind.SELECTION_SETS, ProposalKind.ADD_SKILL}
)


class ProposalStatus(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True, kw_only=True)
class Proposal:
    index: int
    kind: ProposalKind
    summary: str
    payload: Mapping[str, Any]
    status: ProposalStatus = ProposalStatus.OPEN
    decided_by: str | None = None
    decided_at: datetime | None = None
    result: str | None = None  # e.g. the created item or selection id


@dataclass(frozen=True, slots=True, kw_only=True)
class TurnContext:
    """Snapshot taken when the user asks, so the worker reads nothing else."""

    items: Sequence[Mapping[str, Any]] = ()  # itemId, revision, state, content, passage
    pages: Sequence[Mapping[str, Any]] = ()  # sourceId, page, text (images loaded by the worker)
    skills: Sequence[Mapping[str, str]] = ()  # skillId, name of the target course
    course_id: str | None = None
    selection: Mapping[str, Any] | None = None  # 40B: the current selection, if any


@dataclass(frozen=True, slots=True, kw_only=True)
class AssistantTurn:
    turn_id: str
    org_id: str
    created_by: str
    mode: TurnMode
    message: str
    status: ImportStatus  # QUEUED → RUNNING → SUCCEEDED | FAILED (same lifecycle as imports)
    created_at: datetime
    updated_at: datetime
    context: TurnContext = field(default_factory=TurnContext)
    item_ids: Sequence[str] = ()
    source_ids: Sequence[str] = ()
    selection_id: str | None = None
    reply: str | None = None
    proposals: Sequence[Proposal] = ()
    error: str | None = None
    tokens_used: int = 0
    lease: ImportLease | None = None
