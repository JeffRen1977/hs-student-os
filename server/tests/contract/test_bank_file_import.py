"""Step 39B: file import into the question bank — sources, pages, leased page-by-page jobs.

Synthetic pages only. A clean text layer goes through the deterministic splitter; other pages
go to the `question-extraction` ability (a scripted provider here). Every page commits its
items and progress fenced by the job lease; keys from answer-key pages are matched by number;
budgets are charged to the organization.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.domain.bank_import_service import ImportProcessor, PageResult, StaleLease
from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.bank import FetchedLink
from tests.support import Harness, ScriptedProvider, build_harness

AUTHOR, REVIEWER, OTHER, STUDENT = "author_hsos", "reviewer_hsos", "author_sample", "stu_alex"
ORG = "org_hsos_content"
SOURCES, IMPORTS, ITEMS = "/api/bank/sources", "/api/bank/imports", "/api/bank/items"
PNG = "".join(
    (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk",
        "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
    )
)
PAGE_1 = """Questions 1-2 refer to the following passage.
A synthetic passage about a school garden.

1. What does the passage describe?
A) a garden
B) a library
C) a gym
D) a lab
2. Who waters the plants?
A) students B) robots C) nobody D) rain
3. If 2x = 10, what is x?
A) 2
B) 5
C) 8
D) 20
"""
PAGE_2 = "Answer Key\n1. A  2. A  3. B\n"
EXTRACTION = {
    "pageKind": "questions",
    "questions": [
        {"number": 7, "stem": "[Bar graph: 3 bars] Which bar is tallest?",
         "choices": {"A": "first", "B": "second", "C": "third", "D": "all equal"},
         "answer": None, "passageRef": None, "flags": ["figure-described", "made-up-flag"]},
        {"number": 8, "stem": "What is 7/2 as a decimal?", "choices": None, "answer": None,
         "passageRef": "p1", "flags": []},
    ],
    "passages": [{"ref": "p1", "title": "Questions 5-6 refer to …", "text": "Text", "rangeFrom": 5,
                  "rangeTo": 6}],
    "answerKey": [],
}  # fmt: skip


class FakeLinks:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch(self, url: str) -> FetchedLink:
        self.calls.append(url)
        if "private" in url:
            from app.domain.errors import ErrorCode

            raise DomainError(ErrorCode.IMPORT_SOURCE_REJECTED, "private address")
        return FetchedLink(url=url, content_type="text/html", text=PAGE_1)


def make(
    clean_env: pytest.MonkeyPatch, *replies: Any, **settings: Any
) -> tuple[Harness, ScriptedProvider]:
    provider = ScriptedProvider(*replies)
    h = build_harness(clean_env, llm_provider=provider, link_fetcher=FakeLinks(), **settings)  # type: ignore[arg-type]
    return h, provider


async def call(h: Harness, method: str, path: str, uid: str, status: int, body: Any = None) -> Any:
    if method == "GET":
        r = await h.client.get(path, headers=h.auth(uid))
    elif method == "PUT":
        r = await h.client.put(path, json=body, headers=h.auth(uid))
    else:
        r = await h.client.request(method, path, json=body or {}, headers=h.cmd(uid))
    assert r.status_code == status, r.text
    return r.json()


async def pdf(h: Harness, *pages: dict[str, Any], title: str = "Synthetic worksheet") -> str:
    src = await call(
        h, "POST", SOURCES, AUTHOR, 201, {"kind": "pdf", "title": title, "pageCount": len(pages)}
    )
    for n, page in enumerate(pages, start=1):
        await call(h, "PUT", f"{SOURCES}/{src['sourceId']}/pages/{n}", AUTHOR, 200, page)
    return str(src["sourceId"])


async def run(h: Harness, sid: str, **extra: Any) -> dict[str, Any]:
    job = await call(h, "POST", IMPORTS, AUTHOR, 202, {"sourceIds": [sid], **extra})
    assert job["status"] == "QUEUED" and [p["status"] for p in job["pages"]] == ["pending"] * len(
        job["pages"]
    )
    await h.services.import_processor.process_due()
    return await call(h, "GET", f"{IMPORTS}/{job['jobId']}", AUTHOR, 200)  # type: ignore[no-any-return]


async def item(h: Harness, iid: str) -> dict[str, Any]:
    return await call(h, "GET", f"{ITEMS}/{iid}", AUTHOR, 200)  # type: ignore[no-any-return]


async def test_text_layer_pages_split_and_answer_key_pages_fill_keys(
    clean_env: pytest.MonkeyPatch,
) -> None:
    h, provider = make(clean_env)
    sid = await pdf(
        h, {"text": PAGE_1, "mediaType": "image/png", "dataBase64": PNG}, {"text": PAGE_2}
    )
    job = await run(h, sid, courseId="dsat", keyOrigin="compiled-key")
    assert job["status"] == "SUCCEEDED" and job["itemCount"] == 3 and job["tokensUsed"] == 0
    assert [(p["status"], p["method"]) for p in job["pages"]] == [
        ("done", "text-layer"),
        ("done", "text-layer"),
    ]
    assert provider.calls == []  # no model needed for a clean text layer
    q1, q2, q3 = [await item(h, i) for i in job["itemIds"]]
    assert q1["state"] == "extracted" and q1["courseId"] == "dsat"
    cur = q1["current"]
    assert (cur["answer"], cur["answerSource"]) == ("A", "compiled-key")
    assert "key-from-answer-page" in cur["flags"] and f"import:{job['jobId']}" in cur["flags"]
    assert cur["provenance"] == {
        "kind": "imported", "sourceId": sid, "page": 1, "region": "question 1",
        "importJobId": job["jobId"], "reference": "Synthetic worksheet",
    }  # fmt: skip
    assert cur["passageId"] == q2["current"]["passageId"] and q3["current"]["passageId"] is None
    assert q3["current"]["answer"] == "B"
    # the page image is kept for side-by-side review; pages are frozen now
    page = await call(h, "GET", f"{SOURCES}/{sid}/pages/1", AUTHOR, 200)
    assert page["dataBase64"] == PNG and page["text"].startswith("Questions 1-2")
    await call(h, "PUT", f"{SOURCES}/{sid}/pages/1", AUTHOR, 409, {"text": "changed"})
    await call(h, "POST", IMPORTS, AUTHOR, 409, {"sourceIds": [sid]})
    assert await h.services.import_processor.process_due() == 0  # nothing left to do


async def test_image_pages_go_to_the_extraction_ability(clean_env: pytest.MonkeyPatch) -> None:
    h, provider = make(clean_env, EXTRACTION)
    sid = await pdf(h, {"mediaType": "image/png", "dataBase64": PNG})
    job = await run(h, sid)
    assert job["status"] == "SUCCEEDED" and job["itemCount"] == 2 and job["tokensUsed"] == 150
    assert job["pages"][0]["method"] == "vision"
    (call_args,) = provider.calls
    (message,) = call_args["messages"]
    assert message.images[0].data_base64 == PNG
    graph, decimal = [await item(h, i) for i in job["itemIds"]]
    g = graph["current"]
    assert g["figure"] == "described" and "figure-described" in g["flags"]
    assert "made-up-flag" not in g["flags"] and "key-missing" in g["flags"]
    d = decimal["current"]
    assert d["type"] == "spr" and d["passageId"] is None  # question 8 is outside 5-6
    usage = h.store.raw(f"orgs/{ORG}/usage/run-{job['jobId']}")
    assert usage["usedTokens"] == 150


async def test_unusable_model_output_fails_the_page_in_plain_language(
    clean_env: pytest.MonkeyPatch,
) -> None:
    h, _ = make(clean_env, "not json", "still not json", "nope")
    sid = await pdf(h, {"mediaType": "image/png", "dataBase64": PNG})
    job = await run(h, sid)
    assert job["status"] == "FAILED" and job["pages"][0]["status"] == "failed"
    assert job["pages"][0]["error"].startswith("The model's reading of this page could not be used")
    assert job["itemCount"] == 0


async def test_an_exhausted_organization_budget_stops_the_job(
    clean_env: pytest.MonkeyPatch,
) -> None:
    h, provider = make(clean_env, org_job_token_budget=1_000)
    sid = await pdf(h, {"mediaType": "image/png", "dataBase64": PNG})
    job = await run(h, sid)
    assert job["status"] == "FAILED" and "model budget for imports is used up" in job["errors"][-1]
    assert provider.calls == []  # refused before the provider was contacted


async def test_sources_pages_and_jobs_are_organization_scoped(
    clean_env: pytest.MonkeyPatch,
) -> None:
    h, _ = make(clean_env)
    sid = await pdf(h, {"text": PAGE_1})
    for path in (f"{SOURCES}/{sid}", f"{SOURCES}/{sid}/pages/1"):
        await call(h, "GET", path, OTHER, 404)
        await call(h, "GET", path, STUDENT, 403)
    await call(h, "PUT", f"{SOURCES}/{sid}/pages/1", OTHER, 404, {"text": "x"})
    await call(h, "POST", IMPORTS, OTHER, 404, {"sourceIds": [sid]})
    job = await call(h, "POST", IMPORTS, REVIEWER, 202, {"sourceIds": [sid]})  # same organization
    await call(h, "GET", f"{IMPORTS}/{job['jobId']}", OTHER, 404)


async def test_pages_are_checked_before_a_job_starts(clean_env: pytest.MonkeyPatch) -> None:
    h, _ = make(clean_env)
    src = await call(
        h, "POST", SOURCES, AUTHOR, 201, {"kind": "pdf", "title": "Two pages", "pageCount": 2}
    )
    sid = src["sourceId"]
    await call(h, "PUT", f"{SOURCES}/{sid}/pages/1", AUTHOR, 200, {"text": PAGE_1})
    await call(h, "PUT", f"{SOURCES}/{sid}/pages/3", AUTHOR, 400, {"text": "x"})
    await call(h, "PUT", f"{SOURCES}/{sid}/pages/2", AUTHOR, 400, {})  # neither image nor text
    err = await call(h, "POST", IMPORTS, AUTHOR, 400, {"sourceIds": [sid]})
    assert "pages [2] are not uploaded yet" in err["error"]["message"]
    bad = {"mediaType": "image/png", "dataBase64": "aGVsbG8="}  # not a PNG
    await call(h, "PUT", f"{SOURCES}/{sid}/pages/2", AUTHOR, 400, bad)


async def test_text_and_link_sources_are_one_page_each(clean_env: pytest.MonkeyPatch) -> None:
    h, _ = make(clean_env)
    text = await call(
        h, "POST", SOURCES, AUTHOR, 201, {"kind": "text", "title": "Pasted", "text": PAGE_1}
    )
    assert text["pageCount"] == 1 and text["pagesUploaded"] == 1
    link = await call(
        h,
        "POST",
        SOURCES,
        AUTHOR,
        201,
        {"kind": "link", "title": "Web", "url": "https://example.org/q"},
    )
    assert link["url"] == "https://example.org/q"
    job = await run(h, link["sourceId"])
    assert job["itemCount"] == 3
    err = await call(
        h,
        "POST",
        SOURCES,
        AUTHOR,
        422,
        {"kind": "link", "title": "x", "url": "http://private.test/"},
    )
    assert err["error"]["code"] == "IMPORT_SOURCE_REJECTED"


async def test_link_source_replay_does_not_fetch_the_remote_page_again(
    clean_env: pytest.MonkeyPatch,
) -> None:
    links = FakeLinks()
    h = build_harness(clean_env, link_fetcher=links)
    body = {"kind": "link", "title": "Web", "url": "https://example.org/q"}
    headers = h.cmd(AUTHOR, "link-create-retry")
    first = await h.client.post(SOURCES, json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert links.calls == [body["url"]]
    links.calls.clear()

    async def unavailable(url: str) -> FetchedLink:
        raise DomainError(ErrorCode.IMPORT_SOURCE_REJECTED, "The page is gone.")

    links.fetch = unavailable  # type: ignore[method-assign]
    replay = await h.client.post(SOURCES, json=body, headers=headers)
    assert replay.status_code == 201, replay.text
    assert replay.json()["sourceId"] == first.json()["sourceId"]
    assert replay.headers["idempotency-replayed"] == "true"


async def test_a_worker_that_lost_its_lease_cannot_commit(clean_env: pytest.MonkeyPatch) -> None:
    h, _ = make(clean_env)
    sid = await pdf(h, {"text": PAGE_1})
    job = await call(h, "POST", IMPORTS, AUTHOR, 202, {"sourceIds": [sid]})
    proc: ImportProcessor = h.services.import_processor
    claimed = await proc._claim(ORG, job["jobId"], "lease-old")
    assert claimed is not None
    assert await proc._claim(ORG, job["jobId"], "lease-other") is None  # lease still held
    h.clock.advance(seconds=600)  # the first worker stalls past its lease
    await proc.run_job(ORG, job["jobId"])  # a second worker takes over and finishes
    with pytest.raises(StaleLease):
        await proc._commit_page(ORG, job["jobId"], "lease-old", 0, PageResult(method="text-layer"))
    done = await call(h, "GET", f"{IMPORTS}/{job['jobId']}", AUTHOR, 200)
    assert done["status"] == "SUCCEEDED" and done["itemCount"] == 3


async def test_the_browser_may_send_page_uploads(clean_env: pytest.MonkeyPatch) -> None:
    """The bank page uploads pages with PUT; the CORS preflight must allow it."""
    h, _ = make(clean_env, cors_allowed_origins=["http://localhost:8000"])
    r = await h.client.options(
        f"{SOURCES}/src_x/pages/1",
        headers={"Origin": "http://localhost:8000", "Access-Control-Request-Method": "PUT"},
    )
    assert r.status_code == 200 and "PUT" in r.headers["access-control-allow-methods"]
