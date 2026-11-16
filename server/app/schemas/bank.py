"""Question bank API contract (Step 45, API.md §6.5.7, doc/QUESTION_BANK.md)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.schemas.common import ApiModel, CourseId, RequestModel, UtcDatetime
from app.schemas.package import PackageVersionView

ChoiceKey = Literal["A", "B", "C", "D"]
ItemStateValue = Literal[
    "extracted", "draft", "in_review", "approved", "rejected", "discarded", "retired"
]
AnswerSourceValue = Literal["source-key", "compiled-key", "reviewer", "agent-suggested"]
ItemTypeValue = Literal["mc", "spr"]
FigureValue = Literal["none", "described", "image"]
DifficultyValue = Literal["easy", "medium", "hard"]
ProvenanceKindValue = Literal["author", "imported", "agent-drafted"]

Stem = Annotated[str, StringConstraints(max_length=20_000)]
ChoiceText = Annotated[str, StringConstraints(max_length=2_000)]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Answer = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Solution = Annotated[str, StringConstraints(max_length=10_000)]
Notes = Annotated[str, StringConstraints(max_length=2_000)]
RequiredNotes = Annotated[str, StringConstraints(min_length=1, max_length=2_000)]
Tag = Annotated[str, StringConstraints(min_length=1, max_length=60)]
Flag = Annotated[str, StringConstraints(min_length=1, max_length=120)]
SkillRef = Annotated[str, StringConstraints(min_length=1, max_length=120)]
ItemIdStr = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


# ---- Requests ---------------------------------------------------------------------------------


class ItemContentIn(RequestModel):
    section: ShortText | None = None
    skill_ids: list[SkillRef] = Field(default_factory=list, max_length=20)
    difficulty: DifficultyValue | None = None
    passage_id: ItemIdStr | None = None
    stem: Stem = ""
    type: ItemTypeValue = "mc"
    choices: dict[ChoiceKey, ChoiceText] | None = None
    answer: Answer | None = None
    answer_source: AnswerSourceValue | None = None
    solution: Solution | None = None
    figure: FigureValue = "none"
    flags: list[Flag] = Field(default_factory=list, max_length=50)


class ProvenanceIn(RequestModel):
    kind: ProvenanceKindValue = "author"
    source_id: ItemIdStr | None = None
    page: Annotated[int, Field(ge=1, le=10_000)] | None = None
    region: ShortText | None = None
    reference: ShortText | None = None


class CreateItemRequest(RequestModel):
    course_id: CourseId | None = None
    tags: list[Tag] = Field(default_factory=list, max_length=30)
    content: ItemContentIn
    provenance: ProvenanceIn | None = None


class ItemChangesIn(RequestModel):
    """Only the fields present in the request change; `null` clears an optional field."""

    course_id: CourseId | None = None
    tags: list[Tag] | None = Field(default=None, max_length=30)
    section: ShortText | None = None
    skill_ids: list[SkillRef] | None = Field(default=None, max_length=20)
    difficulty: DifficultyValue | None = None
    passage_id: ItemIdStr | None = None
    stem: Stem | None = None
    type: ItemTypeValue | None = None
    choices: dict[ChoiceKey, ChoiceText] | None = None
    answer: Answer | None = None
    answer_source: AnswerSourceValue | None = None
    solution: Solution | None = None
    figure: FigureValue | None = None
    flags: list[Flag] | None = Field(default=None, max_length=50)


class EditItemRequest(RequestModel):
    expected_revision: Annotated[int, Field(ge=1)]
    changes: ItemChangesIn


class KeyRequest(RequestModel):
    answer: Answer
    solution: Solution | None = None


class ApproveItemRequest(RequestModel):
    notes: Notes = ""


class NotesRequest(RequestModel):
    notes: RequiredNotes


class DiscardRequest(RequestModel):
    notes: Notes = ""


# ---- Views --------------------------------------------------------------------------------------


class ProvenanceView(ApiModel):
    kind: ProvenanceKindValue
    source_id: str | None
    page: int | None
    region: str | None
    import_job_id: str | None
    reference: str | None


class ItemReviewView(ApiModel):
    reviewer_id: str
    decision: Literal["approved", "rejected"]
    decided_at: UtcDatetime
    notes: str


class ItemVersionView(ApiModel):
    number: int
    state: ItemStateValue
    section: str | None
    skill_ids: list[str]
    difficulty: str | None
    passage_id: str | None
    stem: str
    type: ItemTypeValue
    choices: dict[str, str] | None
    answer: str | None
    answer_source: AnswerSourceValue | None
    solution: str | None
    figure: FigureValue
    flags: list[str]
    provenance: ProvenanceView
    created_by: str
    created_at: UtcDatetime
    updated_at: UtcDatetime
    submitted_by: str | None
    submitted_at: UtcDatetime | None
    review: ItemReviewView | None


class ItemChangeView(ApiModel):
    action: str
    version: int
    actor_id: str
    at: UtcDatetime
    from_state: ItemStateValue | None
    to_state: ItemStateValue | None
    notes: str


class BankItemSummaryView(ApiModel):
    item_id: str
    course_id: str | None
    state: ItemStateValue
    current_version: int
    approved_version: int | None
    revision: int
    tags: list[str]
    flags: list[str]
    updated_at: UtcDatetime


class BankItemView(BankItemSummaryView):
    org_id: str
    created_by: str
    created_at: UtcDatetime
    current: ItemVersionView
    versions: list[ItemVersionView] = Field(default_factory=list)
    history: list[ItemChangeView]


class BankPassageView(ApiModel):
    passage_id: str
    title: str
    text: str
    provenance: ProvenanceView
    flags: list[str]
    created_by: str
    created_at: UtcDatetime


class BankMemberView(ApiModel):
    """Who is using the bank (Step 45.5): the portal shows reviewer actions only when
    `canReview` is true. The server still enforces every permission."""

    uid: str
    role: Literal["author", "content_reviewer"]
    org_id: str
    can_review: bool


class BankItemListView(ApiModel):
    items: list[BankItemSummaryView]
    next_cursor: str | None


# ---- Selections (Step 45.4) ---------------------------------------------------------------------

SetId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]
Title = Annotated[str, StringConstraints(min_length=1, max_length=120)]
SourceTypeValue = Literal["original", "licensed"]
SourceText = Annotated[str, StringConstraints(min_length=1, max_length=300)]


class ItemRefIn(RequestModel):
    item_id: ItemIdStr
    version: Annotated[int, Field(ge=1)] | None = None  # None: the current approved version


class SelectionSetIn(RequestModel):
    set_id: SetId
    title: Title
    task_title: Title
    duration_min: Annotated[int, Field(ge=5, le=120)] = 20
    items: list[ItemRefIn] = Field(min_length=1, max_length=10)
    skill_ids: list[SkillRef] = Field(default_factory=list, max_length=20)
    difficulty: DifficultyValue = "medium"


class SelectionIn(RequestModel):
    name: Title
    sets: list[SelectionSetIn] = Field(min_length=1, max_length=150)
    starter_set_ids: list[SetId] = Field(default_factory=list, max_length=20)
    sequence_set_ids: list[SetId] = Field(default_factory=list, max_length=200)
    source_type: SourceTypeValue = "original"
    source_author: SourceText | None = None
    source_license: SourceText | None = None


class CreateSelectionRequest(SelectionIn):
    course_id: CourseId


class UpdateSelectionRequest(RequestModel):
    expected_revision: Annotated[int, Field(ge=1)]
    selection: SelectionIn


class BuildRequest(RequestModel):
    version: Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]


class ItemRefView(ApiModel):
    item_id: str
    version: int


class SelectionSetView(ApiModel):
    set_id: str
    title: str
    task_title: str
    duration_min: int
    items: list[ItemRefView]
    skill_ids: list[str]
    difficulty: str


class SelectionView(ApiModel):
    selection_id: str
    course_id: str
    name: str
    sets: list[SelectionSetView]
    starter_set_ids: list[str]
    sequence_set_ids: list[str]
    source_type: SourceTypeValue
    source_author: str | None
    source_license: str | None
    revision: int
    created_by: str
    created_at: UtcDatetime
    updated_at: UtcDatetime
    built_package_version: str | None
    built_by: str | None
    built_at: UtcDatetime | None


class SelectionListView(ApiModel):
    selections: list[SelectionView]


class BuildView(ApiModel):
    selection: SelectionView
    package: PackageVersionView


# ---- Quick entry and imports (Step 39, QUESTION_BANK.md §7.1) --------------------------------

ImportText = Annotated[str, StringConstraints(min_length=1, max_length=200_000)]
PassageText = Annotated[str, StringConstraints(min_length=1, max_length=60_000)]
PassageRef = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,32}$")]


class ParseRequest(RequestModel):
    format: Literal["text", "csv"] = "text"
    text: ImportText


class ProposedPassageView(ApiModel):
    ref: str
    title: str
    text: str
    range_from: int
    range_to: int


class ItemContentView(ApiModel):
    section: str | None
    skill_ids: list[str]
    difficulty: str | None
    stem: str
    type: str
    choices: dict[str, str] | None
    answer: str | None
    solution: str | None


class ProposedQuestionView(ApiModel):
    number: int
    passage_ref: str | None
    content: ItemContentView
    problems: list[str]
    duplicate_of: str | None


class ParseView(ApiModel):
    questions: list[ProposedQuestionView]
    passages: list[ProposedPassageView]
    problems: list[str]


class BatchPassageIn(RequestModel):
    ref: PassageRef
    title: Annotated[str, StringConstraints(max_length=200)] = ""
    text: PassageText


class BatchQuestionIn(RequestModel):
    number: Annotated[int, Field(ge=1, le=10_000)]
    passage_ref: PassageRef | None = None
    content: ItemContentIn


class BatchSettingsIn(RequestModel):
    course_id: CourseId | None = None
    section: ShortText | None = None
    skill_ids: list[SkillRef] = Field(default_factory=list, max_length=20)
    difficulty: DifficultyValue | None = None
    key_origin: Literal["source-key", "compiled-key"] = "source-key"
    source_title: ShortText | None = None
    source_license: Annotated[str, StringConstraints(max_length=500)] | None = None
    tags: list[Tag] = Field(default_factory=list, max_length=20)


class BatchRequest(RequestModel):
    questions: list[BatchQuestionIn] = Field(min_length=1, max_length=100)
    passages: list[BatchPassageIn] = Field(default_factory=list, max_length=20)
    settings: BatchSettingsIn = Field(default_factory=BatchSettingsIn)
    keep_duplicates: bool = False


class ImportPageView(ApiModel):
    source_id: str
    page: int
    status: str
    item_ids: list[str]
    method: str | None
    error: str | None


class ImportJobView(ApiModel):
    job_id: str
    kind: str
    status: str
    pages: list[ImportPageView] = Field(default_factory=list)
    estimate_tokens: int = 0
    tokens_used: int = 0
    key_origin: str | None = None
    item_count: int
    item_ids: list[str]
    passage_ids: list[str]
    skipped: list[str]
    errors: list[str]
    source_title: str | None
    course_id: str | None
    created_by: str
    created_at: UtcDatetime


class ImportJobListView(ApiModel):
    imports: list[ImportJobView]


# ---- File import (Step 39B) ---------------------------------------------------------------

SourceKindValue = Literal["pdf", "image", "text", "link"]


class CreateSourceRequest(RequestModel):
    kind: SourceKindValue
    title: ShortText
    license: Annotated[str, StringConstraints(max_length=500)] | None = None
    url: Annotated[str, StringConstraints(min_length=8, max_length=2_000)] | None = None
    text: Annotated[str, StringConstraints(max_length=50_000)] | None = None
    page_count: Annotated[int, Field(ge=1, le=200)] | None = None


class SourceView(ApiModel):
    source_id: str
    kind: str
    title: str
    url: str | None
    page_count: int | None
    pages_uploaded: int
    license: str | None
    used_by_job: str | None
    created_at: UtcDatetime


class PageRequest(RequestModel):
    media_type: Literal["image/jpeg", "image/png", "image/webp"] | None = None
    data_base64: Annotated[str, StringConstraints(max_length=820_000)] | None = None
    text: Annotated[str, StringConstraints(max_length=50_000)] | None = None


class PageView(ApiModel):
    source_id: str
    number: int
    media_type: str | None
    data_base64: str | None
    text: str | None


class StartImportRequest(RequestModel):
    source_ids: list[ItemIdStr] = Field(min_length=1, max_length=20)
    course_id: CourseId | None = None
    key_origin: Literal["source-key", "compiled-key"] = "source-key"
