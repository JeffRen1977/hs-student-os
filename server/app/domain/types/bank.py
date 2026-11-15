"""Organization question bank (Step 45, doc/QUESTION_BANK.md).

Questions live in an author organization's bank between raw inputs and course packages.
Authors (and, later, the authoring agent) create and edit items; a content reviewer of the
same organization approves them, supplies missing answer keys and solutions, and selects
approved item versions for a package. Bank records are outside every student's subtree and
never contain student data.

Item states (the state of the item's current version):

    extracted ──confirm──► draft ──submit──► in_review ──approve──► approved ──retire──► retired
        │                    │                   └──reject──► rejected
        └──discard──►  discarded  ◄──discard──┘

Editing a `rejected` or `approved` item opens a new `draft` version; the last approved
version stays usable until the new one is approved. `discarded` is only possible before the
item was ever approved.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

CHOICE_KEYS = ("A", "B", "C", "D")
MAX_STEM_CHARS = 20_000
MAX_CHOICE_CHARS = 2_000


class BankItemState(StrEnum):
    EXTRACTED = "extracted"  # agent/import output, never content until an author confirms
    DRAFT = "draft"  # author is editing
    IN_REVIEW = "in_review"  # waiting for the organization's content reviewer
    APPROVED = "approved"  # usable in a selection
    REJECTED = "rejected"  # reviewer notes for the author; editing opens a new version
    DISCARDED = "discarded"  # dropped before it was ever approved
    RETIRED = "retired"  # no longer selectable; past packages keep their copy


ITEM_TRANSITIONS: Mapping[BankItemState, frozenset[BankItemState]] = {
    BankItemState.EXTRACTED: frozenset({BankItemState.DRAFT, BankItemState.DISCARDED}),
    BankItemState.DRAFT: frozenset({BankItemState.IN_REVIEW, BankItemState.DISCARDED}),
    BankItemState.IN_REVIEW: frozenset({BankItemState.APPROVED, BankItemState.REJECTED}),
    BankItemState.APPROVED: frozenset({BankItemState.RETIRED, BankItemState.DRAFT}),
    BankItemState.REJECTED: frozenset({BankItemState.DRAFT}),
    BankItemState.DISCARDED: frozenset(),
    BankItemState.RETIRED: frozenset(),
}

# States whose current version can be edited in place (no new version).
EDITABLE_IN_PLACE = frozenset({BankItemState.EXTRACTED, BankItemState.DRAFT})
# States where an edit opens a new draft version.
EDIT_OPENS_VERSION = frozenset({BankItemState.APPROVED, BankItemState.REJECTED})


class ItemType(StrEnum):
    MC = "mc"  # four choices A-D, one key
    SPR = "spr"  # student-produced response; accepted values separated by "|"


class AnswerSource(StrEnum):
    SOURCE_KEY = "source-key"  # key found in the supplied material
    COMPILED_KEY = "compiled-key"  # a third party's key (e.g. a compiler's reference answers)
    REVIEWER = "reviewer"  # entered or confirmed by the organization's content reviewer
    AGENT_SUGGESTED = "agent-suggested"  # a suggestion only; never approvable as-is


# Sources an author may record when creating or editing an item. `reviewer` is only set by
# the content reviewer's key command.
AUTHOR_ANSWER_SOURCES = frozenset(
    {AnswerSource.SOURCE_KEY, AnswerSource.COMPILED_KEY, AnswerSource.AGENT_SUGGESTED}
)
APPROVABLE_ANSWER_SOURCES = frozenset(
    {AnswerSource.SOURCE_KEY, AnswerSource.COMPILED_KEY, AnswerSource.REVIEWER}
)


class FigureMode(StrEnum):
    NONE = "none"
    DESCRIBED = "described"  # the figure is written out as text in the stem
    IMAGE = "image"  # needs image attachments (separate platform step)


class ProvenanceKind(StrEnum):
    AUTHOR = "author"  # written by hand in the bank
    IMPORTED = "imported"  # extracted from a supplied source
    AGENT_DRAFTED = "agent-drafted"  # drafted by the authoring agent on request


@dataclass(frozen=True, slots=True, kw_only=True)
class Provenance:
    kind: ProvenanceKind
    source_id: str | None = None
    page: int | None = None
    region: str | None = None  # free-form locator, e.g. "left column, question 12"
    import_job_id: str | None = None
    reference: str | None = None  # e.g. the original file name or test form


@dataclass(frozen=True, slots=True, kw_only=True)
class ItemReview:
    reviewer_id: str
    decision: BankItemState  # APPROVED or REJECTED
    decided_at: datetime
    notes: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class ItemContent:
    """The editable fields of one item version."""

    section: str | None = None
    skill_ids: Sequence[str] = ()
    difficulty: str | None = None  # easy | medium | hard
    passage_id: str | None = None
    stem: str = ""
    item_type: ItemType = ItemType.MC
    choices: Mapping[str, str] | None = None
    answer: str | None = None
    answer_source: AnswerSource | None = None
    solution: str | None = None
    figure: FigureMode = FigureMode.NONE
    flags: Sequence[str] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class BankItemVersion:
    item_id: str
    number: int  # 1, 2, ...
    state: BankItemState
    content: ItemContent
    provenance: Provenance
    created_by: str
    created_at: datetime
    updated_at: datetime
    submitted_by: str | None = None
    submitted_at: datetime | None = None
    review: ItemReview | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ItemChange:
    """One audited change of an item: a state transition, an edit or a key."""

    action: str  # create | edit | confirm | submit | discard | key | approve | reject | retire
    version: int
    actor_id: str
    at: datetime
    from_state: BankItemState | None = None
    to_state: BankItemState | None = None
    notes: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class BankItem:
    """Item header. `state` is the state of `current_version`; `approved_version` is the
    latest approved version (or None), the one a selection may use."""

    item_id: str
    org_id: str
    course_id: str | None
    state: BankItemState
    current_version: int
    approved_version: int | None
    revision: int  # optimistic concurrency: bumped on every write
    tags: Sequence[str]
    flags: Sequence[str]  # copy of the current version's flags, for filtering
    created_by: str
    created_at: datetime
    updated_at: datetime
    history: Sequence[ItemChange] = field(default_factory=tuple)


# ---- Later Step 45 / Step 39 records (contract defined, services not yet implemented) -------


class SourceKind(StrEnum):
    IMAGE = "image"
    PDF = "pdf"
    TEXT = "text"
    LINK = "link"
    BANK_JSONL = "bank-jsonl"  # dev-only seeding from a local bank file


@dataclass(frozen=True, slots=True, kw_only=True)
class BankSource:
    source_id: str
    org_id: str
    kind: SourceKind
    title: str
    uploaded_by: str
    created_at: datetime
    storage_path: str | None = None
    url: str | None = None
    fetched_at: datetime | None = None
    content_hash: str | None = None
    text: str | None = None
    page_count: int | None = None
    license: str | None = None  # recorded, not enforced (owner decision 2026-11-15)
    attribution: str | None = None


class ImportStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportJob:
    job_id: str
    org_id: str
    source_ids: Sequence[str]
    status: ImportStatus
    created_by: str
    created_at: datetime
    updated_at: datetime
    course_hint: str | None = None
    run_id: str | None = None
    item_count: int = 0
    errors: Sequence[str] = ()
    tokens_used: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class ItemRef:
    item_id: str
    version: int


@dataclass(frozen=True, slots=True, kw_only=True)
class SelectionSet:
    set_id: str
    title: str
    task_title: str
    duration_min: int
    items: Sequence[ItemRef]


@dataclass(frozen=True, slots=True, kw_only=True)
class Selection:
    selection_id: str
    org_id: str
    course_id: str
    name: str
    sets: Sequence[SelectionSet]
    starter_set_ids: Sequence[str]
    sequence_set_ids: Sequence[str]
    created_by: str
    created_at: datetime
    updated_at: datetime
    revision: int = 1
    built_package_version: str | None = None
