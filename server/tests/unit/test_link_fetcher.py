"""Step 39B: the link guard for `link` sources (no network: fake resolver + mock transport)."""

from __future__ import annotations

from collections.abc import Sequence

import httpx
import pytest

from app.adapters.tools.link_fetcher import HttpLinkFetcher, html_to_text
from app.domain.errors import DomainError

PUBLIC, PRIVATE = "93.184.216.34", "10.0.0.5"


def fetcher(handler: object, hosts: dict[str, Sequence[str]]) -> HttpLinkFetcher:
    async def resolve(host: str) -> Sequence[str]:
        if host not in hosts:
            raise OSError("no such host")
        return hosts[host]

    return HttpLinkFetcher(resolver=resolve, transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def page(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/hop":
        return httpx.Response(302, headers={"location": "http://inside.test/secret"})
    if request.url.path == "/pdf":
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")
    if request.url.path == "/big":
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"x" * 2_100_000)
    html = (
        "<html><style>p{}</style><body><h1>Quiz</h1><p>1. What is 2+2?</p>"
        "<script>x()</script><p>A) 4</p></body></html>"
    )
    return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=html)


async def reason(f: HttpLinkFetcher, url: str) -> str:
    with pytest.raises(DomainError) as e:
        await f.fetch(url)
    assert e.value.code.value == "IMPORT_SOURCE_REJECTED"
    return e.value.message


async def test_public_pages_are_reduced_to_text() -> None:
    f = fetcher(page, {"quiz.test": [PUBLIC]})
    got = await f.fetch("https://quiz.test/q")
    assert got.content_type == "text/html" and got.text == "Quiz\n\n1. What is 2+2?\n\nA) 4"


@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("ftp://quiz.test/q", "Only http and https"),
        ("https://user:pw@quiz.test/q", "user name or password"),
        ("https://quiz.test:8080/q", "standard web ports"),
        ("https://inside.test/q", "private or local network"),
        ("http://127.0.0.1/q", "private or local network"),
        ("http://[::1]/q", "private or local network"),
        ("https://nowhere.test/q", "could not be found"),
        ("https://quiz.test/hop", "private or local network"),  # redirect re-checked
        ("https://quiz.test/pdf", "Only web pages"),
        ("https://quiz.test/big", "larger than 2 MB"),
    ],
)
async def test_the_guard_rejects(url: str, why: str) -> None:
    f = fetcher(page, {"quiz.test": [PUBLIC], "inside.test": [PRIVATE]})
    assert why in await reason(f, url)


async def test_a_host_with_any_private_address_is_rejected() -> None:
    f = fetcher(page, {"mixed.test": [PUBLIC, "192.168.1.9"]})
    assert "private" in await reason(f, "https://mixed.test/q")


def test_html_to_text_keeps_blocks_and_drops_code() -> None:
    assert html_to_text("<div>a</div><div>b<br>c</div><noscript>n</noscript>") == "a\n\nb\nc"
