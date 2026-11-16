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
from datetime import datetime

from app.adapters.firestore.documents import (
    Doc,
    DocTxn,
    DocumentStore,
    Filter,
    GroupReader,
    QuerySpec,
)
from app.adapters.firestore.package_repository import FirestorePlatformIdempotencyStore
from app.domain.ports.bank import BankTx, ItemQuery
from app.domain.types.bank import (
    AnswerSource,
    BankItem,
    BankItemState,
    BankItemVersion,
    BankPassage,
    BankSource,
    FigureMode,
    ImportJob,
    ImportKind,
    ImportLease,
    ImportPage,
    ImportStatus,
    ItemChange,
    ItemContent,
    ItemRef,
    ItemReview,
    ItemType,
    PageStatus,
    Provenance,
    ProvenanceKind,
    Selection,
    SelectionSet,
    SourceKind,
    SourcePage,
    SourceType,
)
from app.domain.types.usage import BudgetScope, Reservation, UsageCounter

ORGS = "orgs"
ITEMS = "bankItems"
PASSAGES = "bankPassages"
SELECTIONS = "selections"
VERSIONS = "versions"
IMPORTS = "imports"
SOURCES = "sources"
PAGES = "pages"
USAGE = "usage"


def _id(value: str) -> str:
    if not value or "/" in value:
        raise ValueError("invalid document id")
    return value


def items_collection(org_id: str) -> str:
    return f"{ORGS}/{_id(org_id)}/{ITEMS}"


def item_path(org_id: str, item_id: str) -> str:
    return f"{items_collection(org_id)}/{_id(item_id)}"


def import_path(org_id: str, job_id: str) -> str:
    return f"{ORGS}/{_id(org_id)}/{IMPORTS}/{_id(job_id)}"


def import_to_doc(j: ImportJob) -> Doc:
    return {
        "jobId": j.job_id,
        "orgId": j.org_id,
        "kind": j.kind.value,
        "sourceIds": list(j.source_ids),
        "status": j.status.value,
        "createdBy": j.created_by,
        "createdAt": j.created_at,
        "updatedAt": j.updated_at,
        "courseHint": j.course_hint,
        "itemCount": j.item_count,
        "itemIds": list(j.item_ids),
        "passageIds": list(j.passage_ids),
        "skipped": list(j.skipped),
        "errors": list(j.errors),
        "tokensUsed": j.tokens_used,
        "sourceTitle": j.source_title,
        "pages": [
            {"sourceId": p.source_id, "page": p.page, "status": p.status.value,
             "itemIds": list(p.item_ids), "method": p.method, "error": p.error}
            for p in j.pages
        ],
        "keyOrigin": j.key_origin.value if j.key_origin else None,
        "answerKey": {str(k): v for k, v in j.answer_key.items()},
        "estimateTokens": j.estimate_tokens,
        "lease": (
            {"workerId": j.lease.worker_id, "token": j.lease.token, "expiresAt": j.lease.expires_at}
            if j.lease
            else None
        ),
    }  # fmt: skip


def import_from_doc(d: Doc) -> ImportJob:
    return ImportJob(
        job_id=d["jobId"],
        org_id=d["orgId"],
        kind=ImportKind(d.get("kind", ImportKind.FILES.value)),
        source_ids=tuple(d.get("sourceIds", [])),
        status=ImportStatus(d["status"]),
        created_by=d["createdBy"],
        created_at=d["createdAt"],
        updated_at=d["updatedAt"],
        course_hint=d.get("courseHint"),
        item_count=int(d.get("itemCount", 0)),
        item_ids=tuple(d.get("itemIds", [])),
        passage_ids=tuple(d.get("passageIds", [])),
        skipped=tuple(d.get("skipped", [])),
        errors=tuple(d.get("errors", [])),
        tokens_used=int(d.get("tokensUsed", 0)),
        source_title=d.get("sourceTitle"),
        pages=tuple(
            ImportPage(
                source_id=p["sourceId"],
                page=int(p["page"]),
                status=PageStatus(p["status"]),
                item_ids=tuple(p.get("itemIds", [])),
                method=p.get("method"),
                error=p.get("error"),
            )
            for p in d.get("pages", [])
        ),
        key_origin=AnswerSource(d["keyOrigin"]) if d.get("keyOrigin") else None,
        answer_key={int(k): v for k, v in (d.get("answerKey") or {}).items()},
        estimate_tokens=int(d.get("estimateTokens", 0)),
        lease=(
            ImportLease(
                worker_id=d["lease"]["workerId"],
                token=d["lease"]["token"],
                expires_at=d["lease"]["expiresAt"],
            )
            if d.get("lease")
            else None
        ),
    )


def source_path(org_id: str, source_id: str) -> str:
    return f"{ORGS}/{_id(org_id)}/{SOURCES}/{_id(source_id)}"


def page_path(org_id: str, source_id: str, number: int) -> str:
    return f"{source_path(org_id, source_id)}/{PAGES}/{number:04d}"


def source_to_doc(x: BankSource) -> Doc:
    return {
        "sourceId": x.source_id, "orgId": x.org_id, "kind": x.kind.value, "title": x.title,
        "uploadedBy": x.uploaded_by, "createdAt": x.created_at, "url": x.url,
        "fetchedAt": x.fetched_at, "contentHash": x.content_hash, "pageCount": x.page_count,
        "license": x.license, "attribution": x.attribution, "usedByJob": x.used_by_job,
    }  # fmt: skip


def source_from_doc(d: Doc) -> BankSource:
    return BankSource(
        source_id=d["sourceId"],
        org_id=d["orgId"],
        kind=SourceKind(d["kind"]),
        title=d["title"],
        uploaded_by=d["uploadedBy"],
        created_at=d["createdAt"],
        url=d.get("url"),
        fetched_at=d.get("fetchedAt"),
        content_hash=d.get("contentHash"),
        page_count=d.get("pageCount"),
        license=d.get("license"),
        attribution=d.get("attribution"),
        used_by_job=d.get("usedByJob"),
    )


def page_to_doc(p: SourcePage) -> Doc:
    return {
        "sourceId": p.source_id, "number": p.number, "mediaType": p.media_type,
        "dataBase64": p.data_base64, "text": p.text, "sizeBytes": p.size_bytes,
    }  # fmt: skip


def page_from_doc(d: Doc) -> SourcePage:
    return SourcePage(
        source_id=d["sourceId"],
        number=int(d["number"]),
        media_type=d.get("mediaType"),
        data_base64=d.get("dataBase64"),
        text=d.get("text"),
        size_bytes=int(d.get("sizeBytes", 0)),
    )


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
        "selectable": i.approved_version is not None and i.state is not BankItemState.RETIRED,
        "revision": i.revision,
        "tags": list(i.tags),
        "flags": list(i.flags),
        "contentHash": i.content_hash,
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
        content_hash=d.get("contentHash"),
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
        if q.approved_only:
            filters.append(Filter("selectable", "==", True))
        if q.content_hashes:
            filters.append(Filter("contentHash", "in", list(q.content_hashes)[:30]))
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


class FirestoreImportJobStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, org_id: str, job_id: str) -> ImportJob | None:
        doc = await self._txn.get(import_path(org_id, job_id))
        return import_from_doc(doc) if doc else None

    async def list_for_org(self, org_id: str, limit: int) -> Sequence[ImportJob]:
        docs = await self._txn.query(
            f"{ORGS}/{_id(org_id)}/{IMPORTS}", QuerySpec(order_by=("createdAt",))
        )
        return [import_from_doc(d) for d in docs][-limit:][::-1]  # newest first

    def save(self, job: ImportJob) -> None:
        self._txn.set(import_path(job.org_id, job.job_id), import_to_doc(job))


class FirestoreSourceStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, org_id: str, source_id: str) -> BankSource | None:
        doc = await self._txn.get(source_path(org_id, source_id))
        return source_from_doc(doc) if doc else None

    def save(self, source: BankSource) -> None:
        self._txn.set(source_path(source.org_id, source.source_id), source_to_doc(source))

    async def get_page(self, org_id: str, source_id: str, number: int) -> SourcePage | None:
        doc = await self._txn.get(page_path(org_id, source_id, number))
        return page_from_doc(doc) if doc else None

    async def page_numbers(self, org_id: str, source_id: str) -> Sequence[int]:
        docs = await self._txn.query(
            f"{source_path(org_id, source_id)}/{PAGES}", QuerySpec(order_by=("number",))
        )
        return [int(d["number"]) for d in docs]

    def save_page(self, org_id: str, page: SourcePage) -> None:
        self._txn.set(page_path(org_id, page.source_id, page.number), page_to_doc(page))


class FirestoreOrgUsageStore:
    def __init__(self, txn: DocTxn) -> None:
        self._txn = txn

    async def get(self, org_id: str, key: str) -> UsageCounter | None:
        d = await self._txn.get(f"{ORGS}/{_id(org_id)}/{USAGE}/{_id(key)}")
        if d is None:
            return None
        return UsageCounter(
            key=d["key"],
            scope=BudgetScope(d["scope"]),
            used_tokens=int(d.get("usedTokens", 0)),
            reservations={
                k: Reservation(tokens=int(v["tokens"]), reserved_at=v["reservedAt"])
                for k, v in d.get("reservations", {}).items()
            },
            updated_at=d.get("updatedAt"),
        )

    def save(self, org_id: str, c: UsageCounter) -> None:
        self._txn.set(
            f"{ORGS}/{_id(org_id)}/{USAGE}/{_id(c.key)}",
            {
                "key": c.key,
                "scope": c.scope.value,
                "usedTokens": c.used_tokens,
                "reservations": {
                    k: {"tokens": r.tokens, "reservedAt": r.reserved_at}
                    for k, r in c.reservations.items()
                },
                "updatedAt": c.updated_at,
            },
        )


class FirestoreImportQueueReader:
    """Due file-import jobs across organizations (collection group `imports`)."""

    def __init__(self, reader: GroupReader) -> None:
        self._reader = reader

    async def due_jobs(self, now: datetime, limit: int) -> Sequence[tuple[str, str]]:
        docs = await self._reader.query_group(
            IMPORTS,
            QuerySpec(
                filters=[
                    Filter("status", "in", [ImportStatus.QUEUED.value, ImportStatus.RUNNING.value])
                ],
                order_by=("createdAt",),
                limit=limit * 4,
            ),
        )
        due = []
        for d in docs:
            lease = d.get("lease")
            if (
                d["status"] == ImportStatus.QUEUED.value
                or lease is None
                or lease["expiresAt"] <= now
            ):
                due.append((d["orgId"], d["jobId"]))
        return due[:limit]


class FirestoreBankTx:
    def __init__(self, txn: DocTxn) -> None:
        self.items = FirestoreBankItemStore(txn)
        self.passages = FirestoreBankPassageStore(txn)
        self.selections = FirestoreSelectionStore(txn)
        self.imports = FirestoreImportJobStore(txn)
        self.sources = FirestoreSourceStore(txn)
        self.org_usage = FirestoreOrgUsageStore(txn)
        self.idempotency = FirestorePlatformIdempotencyStore(txn)


class DocumentBankUnitOfWork:
    def __init__(self, store: DocumentStore) -> None:
        self._store = store

    async def transaction[T](self, fn: Callable[[BankTx], Awaitable[T]]) -> T:
        async def body(txn: DocTxn) -> T:
            return await fn(FirestoreBankTx(txn))

        return await self._store.run_transaction(body)
