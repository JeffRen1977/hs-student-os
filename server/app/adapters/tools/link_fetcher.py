"""Fetch a public web page for a `link` source, under the link guard (Step 39B,
QUESTION_BANK.md §7.2).

- http(s) only, no credentials in the URL, default ports only;
- every address the host resolves to must be public (no private, loopback, link-local,
  multicast, reserved or unspecified addresses), checked before each request;
- redirects are followed by hand (at most 3) and each target is checked again;
- only text/html or text/plain, at most 2 MB, 10 s per request;
- HTML is reduced to readable text (scripts and styles dropped).

Residual risk, accepted for now: the HTTP client resolves the name again after the check, so
a DNS-rebinding host could still answer differently between the check and the request.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Sequence
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from app.domain.errors import DomainError, ErrorCode
from app.domain.ports.bank import FetchedLink

MAX_BYTES = 2_000_000
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 10.0
TEXT_TYPES = ("text/html", "text/plain")

Resolver = Callable[[str], Awaitable[Sequence[str]]]


def _reject(reason: str) -> DomainError:
    return DomainError(ErrorCode.IMPORT_SOURCE_REJECTED, reason)


async def system_resolver(host: str) -> Sequence[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


class _Text(HTMLParser):
    BLOCK = frozenset({"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section",
             "article", "table", "ol", "ul", "pre", "blockquote"})  # fmt: skip

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript", "template"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "template"):
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    lines = [" ".join(line.split()) for line in "".join(parser.parts).split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


class HttpLinkFetcher:
    def __init__(
        self,
        resolver: Resolver = system_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._resolve = resolver
        self._transport = transport

    async def _check(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise _reject("Only http and https links can be imported.")
        if parts.username or parts.password:
            raise _reject("Links with a user name or password are not accepted.")
        if parts.port not in (None, 80, 443):
            raise _reject("Links must use the standard web ports.")
        host = parts.hostname
        if not host:
            raise _reject("The link has no host name.")
        try:
            addresses = [host] if _is_ip(host) else await self._resolve(host)
        except OSError as exc:
            raise _reject("The link's host name could not be found.") from exc
        if not addresses:
            raise _reject("The link's host name could not be found.")
        for a in addresses:
            ip = ipaddress.ip_address(a)
            if not ip.is_global or ip.is_multicast:
                raise _reject("Links to private or local network addresses are not allowed.")

    async def fetch(self, url: str) -> FetchedLink:
        current = url.strip()
        async with httpx.AsyncClient(
            transport=self._transport, timeout=TIMEOUT_SECONDS, follow_redirects=False
        ) as client:
            for _ in range(MAX_REDIRECTS + 1):
                await self._check(current)
                try:
                    async with client.stream("GET", current) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location:
                                raise _reject("The link redirects nowhere.")
                            current = urljoin(current, location)
                            continue
                        if response.status_code != 200:
                            raise _reject(f"The page answered with status {response.status_code}.")
                        ctype = response.headers.get("content-type", "").split(";")[0].strip()
                        if ctype not in TEXT_TYPES:
                            raise _reject("Only web pages and plain-text links can be imported.")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > MAX_BYTES:
                                raise _reject("The page is larger than 2 MB.")
                        text = body.decode(response.encoding or "utf-8", errors="replace")
                        readable = html_to_text(text) if ctype == "text/html" else text.strip()
                        return FetchedLink(url=current, content_type=ctype, text=readable)
                except httpx.TimeoutException as exc:
                    raise _reject("The page took too long to answer.") from exc
                except httpx.HTTPError as exc:
                    raise _reject("The page could not be fetched.") from exc
        raise _reject("The link redirects too many times.")


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True
