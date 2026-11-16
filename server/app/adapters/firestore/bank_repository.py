"""Organization question bank (Step 45, BACKEND.md §3, doc/QUESTION_BANK.md §4).

Layout (outside every student's subtree):

    orgs/{orgId}/bankItems/{itemId}                    item header: state, versions, history
    orgs/{orgId}/bankItems/{itemId}/versions/{n:06d}   one item version (content, review)
    orgs/{orgId}/bankPassages/{passageId}              shared passage / stimulus
    orgs/{orgId}/selections/{selectionId}              a content reviewer's package selection

Commands reuse the platform member idempotency records (`platformMembers/{uid}/idempotency`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from app.adapters.firestore.documents import Doc, DocTxn, DocumentStore, Filter, QuerySpec
from app.adapters.firestore.package_repository import FirestorePlatformIdempotencyStore
from app.domain.ports.bank import BankTx, ItemQuery
from app.domain.types.bank import (
    AnswerSource,
    BankItem,
    BankItemState,
    BankItemVersion,
    BankPassage,
    FigureMode,
    ItemChange,
    ItemContent,
    ItemRef,
    ItemReview,
    ItemType,
    Provenance,
    ProvenanceKind,
    Selection,
    SelectionSet,
    SourceType,
)

ORGS = "orgs"
ITEMS = "bankItems"
PASSAGES = "bankPassages"
SELECTIONS = "selections"
VERSIONS = "versions"


def _id(value: str) -> str:
    if not value or "/" in value:
        raise ValueError("invalid document id")
    return value


def items_collection(org_id: str) -> str:
    return f"{ORGS}/{_id(org_id)}/{ITEMS}"


def item_path(org_id: str, item_id: str) -> str:
    return f"{items_collection(org_id)}/{_id(item_id)}"


def selection_path(org_id: str, selection_id: str) -> str:
    return f"{ORGS}/{_id(org_id)}/{SELECTIONS}/{_id(selection_id)}"


def selection_to_doc(x: Selection) -> Doc:
    return {
        "selectionId": x.selection_id,
        "orgId": x.org_id,
        "courseId": x.course_id,
        "name": x.name,
        "sets": [
            {
                "setId": st.set_id,
                "title": st.title,
                "taskTitle": st.task_title,
                "durationMin": st.duration_min,
                "skillIds": list(st.skill_ids),
                "difficulty": st.difficulty,
                "items": [{"itemId": r.item_id, "version": r.version} for r in st.items],
            }
            for st in x.sets
        ],
        "starterSetIds": list(x.starter_set_ids),
        "sequenceSetIds": list(x.sequence_set_ids),
        "createdBy": x.created_by,
        "createdAt": x.created_at,
        "updatedAt": x.updated_at,
        "revision": x.revision,
        "sourceType": x.source_type.value,
        "sourceAuthor": x.source_author,
        "sourceLicense": x.source_license,
        "builtPackageVersion": x.built_package_version,
        "builtBy": x.built_by,
        "builtAt": x.built_at,
    }


def selection_from_doc(d: Doc) -> Selection:
    return Selection(
        selection_id=d["selectionId"],
        org_id=d["orgId"],
        course_id=d["courseId"],
        name=d["name"],
        sets=tuple(
            SelectionSet(
                set_id=st["setId"],
                title=st["title"],
                task_title=st["taskTitle"],
                duration_min=int(st["durationMin"]),
                skill_ids=tuple(st.get("skillIds", [])),
                difficulty=st.get("difficulty", "medium"),
                items=tuple(
                    ItemRef(item_id=r["itemId"], version=int(r["version"])) for r in st["items"]
                ),
            )
            for st in d.get("sets", [])
        ),
        starter_set_ids=tuple(d.get("starterSetIds", [])),
        sequence_set_ids=tuple(d.get("sequenceSetIds", [])),
        created_by=d["createdBy"],
        created_at=d["createdAt"],
        updated_at=d["updatedAt"],
        revision=int(d.get("revision", 1)),
        source_type=SourceType(d.get("sourceType", "original")),
        source_author=d.get("sourceAuthor"),
        source_license=d.get("sourceLicense"),
        built_package_version=d.get("builtPackageVersion"),
        built_by=d.get("builtBy"),
        built_at=d.get("builtAt"),
    )


def passage_path(org_id: str, passage_id: str) -> str:
    return f"{ORGS}/{_id(org_id)}/{PASSAGES}/{_id(passage_id)}"


def passage_to_doc(p: BankPassage) -> Doc:
    return {
        "passageId": p.passage_id,
        "orgId": p.org_id,
        "title": p.title,
        "text": p.text,
        "provenance": provenance_to_doc(p.provenance),
        "createdBy": p.created_by,
        "createdAt": p.created_at,
        "flags": list(p.flags),
    }


def passage_from_doc(d: Doc) -> BankPassage:
    return BankPassage(
        passage_id=d["passageId"],
        org_id=d["orgId"],
        title=d.get("title", ""),
        text=d.get("text", ""),
        provenance=provenance_from_doc(d["provenance"]),
        created_by=d["createdBy"],
        created_at=d["createdAt"],
        flags=tuple(d.get("flags", [])),
    )


def version_path(org_id: str, item_id: str, number: int) -> str:
    return f"{item_path(org_id, item_id)}/{VERSIONS}/{number:06d}"


# ---- Serialization ------------------------------------------------------------------------


def content_to_doc(c: ItemContent) -> Doc:
    return {
        "section": c.section,
        "skillIds": list(c.skill_ids),
        "difficulty": c.difficulty,
        "passageId": c.passage_id,
        "stem": c.stem,
        "type": c.item_type.value,
        "choices": dict(c.choices) if c.choices is not None else None,
        "answer": c.answer,
        "answerSource": c.answer_source.value if c.answer_source else None,
        "solution": c.solution,
        "figure": c.figure.value,
        "flags": list(c.flags),
    }


def content_from_doc(d: Doc) -> ItemContent:
    return ItemContent(
        section=d.get("section"),
        skill_ids=tuple(d.get("skillIds", [])),
        difficulty=d.get("difficulty"),
        passage_id=d.get("passageId"),
        stem=d.get("stem", ""),
        item_type=ItemType(d.get("type", "mc")),
        choices=dict(d["choices"]) if d.get("choices") is not None else None,
        answer=d.get("answer"),
        answer_source=AnswerSource(d["answerSource"]) if d.get("answerSource") else None,
        solution=d.get("solution"),
        figure=FigureMode(d.get("figure", "none")),
        flags=tuple(d.get("flags", [])),
    )


def provenance_to_doc(p: Provenance) -> Doc:
    return {
        "kind": p.kind.value,
        "sourceId": p.source_id,
        "page": p.page,
        "region": p.region,
        "importJobId": p.import_job_id,
        "reference": p.reference,
    }


def provenance_from_doc(d: Doc) -> Provenance:
    return Provenance(
        kind=ProvenanceKind(d["kind"]),
        source_id=d.get("sourceId"),
        page=d.get("page"),
        region=d.get("region"),
        import_job_id=d.get("importJobId"),
        reference=d.get("reference"),
    )


def version_to_doc(v: BankItemVersion) -> Doc:
    r = v.review
    return {
        "itemId": v.item_id,
        "number": v.number,
        "state": v.state.value,
        "content": content_to_doc(v.content),
        "provenance": provenance_to_doc(v.provenance),
        "createdBy": v.created_by,
        "createdAt": v.created_at,
        "updatedAt": v.updated_at,
        "submittedBy": v.submitted_by,
        "submittedAt": v.submitted_at,
        "review": None
        if r is None
        else {
            "reviewerId": r.reviewer_id,
            "decision": r.decision.value,
            "decidedAt": r.decided_at,
            "notes": r.notes,
        },
    }


def version_from_doc(d: Doc) -> BankItemVersion:
    r = d.get("review")
    return BankItemVersion(
        item_id=d["itemId"],
        number=int(d["number"]),
        state=BankItemState(d["state"]),
        content=content_from_doc(d["content"]),
        provenance=provenance_from_doc(d["provenance"]),
        created_by=d["createdBy"],
        created_at=d["createdAt"],
        updated_at=d["updatedAt"],
        submitted_by=d.get("submittedBy"),
        submitted_at=d.get("submittedAt"),
        review=None
        if r is None
        else ItemReview(
            reviewer_id=r["reviewerId"],
            decision=BankItemState(r["decision"]),
            decided_at=r["decidedAt"],
            notes=r.get("notes", ""),
        ),
    )


def item_to_doc(i: BankItem) -> Doc:
    return {
        "itemId": i.item_id,
        "orgId": i.org_id,
        "courseId": i.course_id,
        "state": i.state.value,
        "currentVersion": i.current_version,
        "approvedVersion": i.approved_version,
        "revision": i.revision,
        "tags": list(i.tags),
        "flags": list(i.flags),
        "createdBy": i.created_by,
        "createdAt": i.created_at,
        "updatedAt": i.updated_at,
        "history": [
            {
                "action": h.action,
                "version": h.version,
                "actorId": h.actor_id,
                "at": h.at,
                "from": h.from_state.value if h.from_state else None,
                "to": h.to_state.value if h.to_state else None,
                "notes": h.notes,
            }
            for h in i.history
        ],
    }


def item_from_doc(d: Doc) -> BankItem:
    return BankItem(
        item_id=d["itemId"],
        org_id=d["orgId"],
        course_id=d.get("courseId"),
        state=BankItemState(d["state"]),
        current_version=int(d["currentVersion"]),
        approved_version=d.get("approvedVersion"),
        revision=int(d["revision"]),
        tags=tuple(d.get("tags", [])),
        flags=tuple(d.get("flags", [])),
        created_by=d["createdBy"],
        created_at=d["createdAt"],
        updated_at=d["updatedAt"],
        history=tuple(
            ItemChange(
                action=h["action"],
                version=int(h["version"]),
                actor_id=h["actorId"],
                at=h["at"],
                from_state=BankItemState(h["from"]) if h.get("from") else None,
                to_state=BankItemState(h["to"]) if h.get("to") else None,
                notes=h.get("notes", ""),
            )
            for h in d.get("history", [])
        ),
    )


# ---- Stores ---------------------------------------------------------------------------------


class FirestoreBankItemStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, org_id: str, item_id: str) -> BankItem | None:
        doc = await self._txn.get(item_path(org_id, item_id))
        return item_from_doc(doc) if doc else None

    async def get_version(self, org_id: str, item_id: str, number: int) -> BankItemVersion | None:
        doc = await self._txn.get(version_path(org_id, item_id, number))
        return version_from_doc(doc) if doc else None

    async def list_versions(self, org_id: str, item_id: str) -> Sequence[BankItemVersion]:
        docs = await self._txn.query(
            f"{item_path(org_id, item_id)}/{VERSIONS}", QuerySpec(order_by=("number",))
        )
        return [version_from_doc(d) for d in docs]

    async def query(self, org_id: str, q: ItemQuery) -> Sequence[BankItem]:
        filters: list[Filter] = []
        if q.state is not None:
            filters.append(Filter("state", "==", q.state.value))
        if q.course_id is not None:
            filters.append(Filter("courseId", "==", q.course_id))
        if q.flag is not None:
            filters.append(Filter("flags", "array_contains", q.flag))
        docs = await self._txn.query(
            items_collection(org_id),
            QuerySpec(
                filters=tuple(filters),
                order_by=("itemId",),
                start_after=(q.after_item_id,) if q.after_item_id else None,
                limit=q.limit,
            ),
        )
        return [item_from_doc(d) for d in docs]

    def save(self, item: BankItem) -> None:
        self._txn.set(item_path(item.org_id, item.item_id), item_to_doc(item))

    def save_version(self, org_id: str, version: BankItemVersion) -> None:
        self._txn.set(
            version_path(org_id, version.item_id, version.number), version_to_doc(version)
        )


class FirestoreBankPassageStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, org_id: str, passage_id: str) -> BankPassage | None:
        doc = await self._txn.get(passage_path(org_id, passage_id))
        return passage_from_doc(doc) if doc else None

    def save(self, passage: BankPassage) -> None:
        self._txn.set(passage_path(passage.org_id, passage.passage_id), passage_to_doc(passage))


class FirestoreSelectionStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, org_id: str, selection_id: str) -> Selection | None:
        doc = await self._txn.get(selection_path(org_id, selection_id))
        return selection_from_doc(doc) if doc else None

    async def list_for_org(self, org_id: str) -> Sequence[Selection]:
        docs = await self._txn.query(
            f"{ORGS}/{_id(org_id)}/{SELECTIONS}", QuerySpec(order_by=("selectionId",), limit=200)
        )
        return [selection_from_doc(d) for d in docs]

    def save(self, selection: Selection) -> None:
        self._txn.set(
            selection_path(selection.org_id, selection.selection_id), selection_to_doc(selection)
        )


class FirestoreBankTx:
    def __init__(self, txn: DocTxn) -> None:
        self.items = FirestoreBankItemStore(txn)
        self.passages = FirestoreBankPassageStore(txn)
        self.selections = FirestoreSelectionStore(txn)
        self.idempotency = FirestorePlatformIdempotencyStore(txn)


class DocumentBankUnitOfWork:
    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    async def transaction[T](self, fn: Callable[[BankTx], Awaitable[T]]) -> T:
        async def body(txn: DocTxn) -> T:
            return await fn(FirestoreBankTx(txn))

        return await self._store.run_transaction(body)
