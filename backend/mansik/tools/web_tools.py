"""Web tools — outbound search & fetch.

web.search: Tavily API (if MANISK_TAVILY_API_KEY set) or DuckDuckGo's
HTML endpoint as a keyless fallback. Both are REAL integrations; if the
network is restricted the tool returns an honest error.

web.fetch: hardened HTTP GET — private/loopback/link-local IP ranges are
blocked (SSRF), response size capped, content-type allowlist, timeout.
"""

from __future__ import annotations

import html as html_lib
import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx

from ..config import RISK_EXTERNAL_COMM, get_settings
from ..errors import AppError, ValidationAppError
from .base import Tool, ToolContext, ToolParams
from pydantic import Field

USER_AGENT = "MANISK-Personal-AI/0.1 (+https://github.com/lovkettiwari478-cmd/Mansik-Personal-AI-Assistant-)"


class SearchParams(ToolParams):
    query: str = Field(..., min_length=2, max_length=300)


class FetchParams(ToolParams):
    url: str = Field(..., min_length=10, max_length=2000)


_PRIVATE_HOSTS_MESSAGE = "Blocked: target resolves to a private or local address."


def _assert_public_url(url: str) -> None:
    """SSRF protection: only public http(s) URLs on standard ports."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValidationAppError("Only http(s) URLs are allowed.")
    if parsed.username or parsed.password:
        raise ValidationAppError("Credentials in URLs are not allowed.")
    if parsed.port is not None and parsed.port not in (80, 443, 8080, 8443):
        raise ValidationAppError("Non-standard ports are not allowed.")
    host = parsed.hostname
    if not host:
        raise ValidationAppError("Invalid URL.")
    # Resolve and check every address (defeats DNS-based SSRF tricks).
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise ValidationAppError("Could not resolve host.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        ):
            raise ValidationAppError(_PRIVATE_HOSTS_MESSAGE)


async def _tavily_search(query: str, api_key: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={"api_key": api_key, "query": query, "max_results": 5, "search_depth": "basic"},
            )
    except httpx.HTTPError as exc:
        raise AppError(
            f"Search provider unreachable from this deployment ({type(exc).__name__}).",
            code="search_error",
        )
    if resp.status_code != 200:
        raise AppError(f"Search provider error (HTTP {resp.status_code}).", code="search_error")
    data = resp.json()
    return [
        {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")[:400]}
        for r in data.get("results", [])
    ]


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(raw: str) -> str:
    text = html_lib.unescape(_TAG_RE.sub(" ", raw))
    return _WS_RE.sub(" ", text).strip()


async def _duckduckgo_search(query: str) -> list[dict]:
    """Keyless fallback: DuckDuckGo HTML endpoint (unofficial, may rate-limit)."""
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en"}
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=headers) as client:
            resp = await client.get("https://html.duckduckgo.com/html/", params={"q": query})
    except httpx.HTTPError as exc:
        raise AppError(
            f"Search backend unreachable from this deployment ({type(exc).__name__}) — "
            "the network may be restricted.",
            code="search_error",
        )
    if resp.status_code != 200:
        raise AppError(f"Search backend unavailable (HTTP {resp.status_code}).", code="search_error")
    results = []
    # result links look like <a rel="nofollow" class="result__a" href="...">title</a>
    for m in re.finditer(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', resp.text, re.S
    ):
        url, title = m.group(1), _strip_html(m.group(2))
        # DDG wraps URLs: extract uddg param
        um = re.search(r"uddg=([^&]+)", url)
        if um:
            from urllib.parse import unquote
            url = unquote(um.group(1))
        if title and url.startswith("http"):
            results.append({"title": title[:200], "url": url, "snippet": ""})
        if len(results) >= 5:
            break
    if not results:
        raise AppError("Search backend returned no results (it may be rate-limited or blocked).", code="search_error")
    return results


class WebSearchTool(Tool):
    id = "web.search"
    name = "Web search"
    description = "Search the public web and return top results with titles, URLs and snippets."
    category = "web"
    risk = RISK_EXTERNAL_COMM
    scope = "tools:web"
    timeout_seconds = 25.0
    params_model = SearchParams

    def available(self, ctx: ToolContext) -> bool:
        settings = get_settings()
        return bool(settings.tavily_api_key) or settings.allow_duckduckgo_search

    def unavailable_reason(self) -> str:
        return "No search backend configured (set MANISK_TAVILY_API_KEY or enable the keyless DuckDuckGo fallback)."

    async def run(self, ctx: ToolContext, params: SearchParams) -> dict:
        settings = get_settings()
        backend = "duckduckgo"
        if settings.tavily_api_key:
            backend = "tavily"
            try:
                results = await _tavily_search(params.query, settings.tavily_api_key)
            except AppError:
                if settings.allow_duckduckgo_search:
                    backend = "duckduckgo"
                    results = await _duckduckgo_search(params.query)
                else:
                    raise
        else:
            results = await _duckduckgo_search(params.query)
        return {"query": params.query, "backend": backend, "results": results}


class WebFetchTool(Tool):
    id = "web.fetch"
    name = "Fetch URL"
    description = "Fetch a public web page and return its readable text (SSRF-protected, size-limited)."
    category = "web"
    risk = RISK_EXTERNAL_COMM
    scope = "tools:web"
    timeout_seconds = 25.0
    params_model = FetchParams

    def available(self, ctx: ToolContext) -> bool:
        return get_settings().http_fetch_enabled

    def unavailable_reason(self) -> str:
        return "URL fetching is disabled in this deployment (MANISK_HTTP_FETCH_ENABLED=false)."

    async def run(self, ctx: ToolContext, params: FetchParams) -> dict:
        _assert_public_url(params.url)
        settings = get_settings()
        try:
            async with httpx.AsyncClient(
                timeout=20.0, follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                resp = await client.get(params.url)
        except httpx.HTTPError as exc:
            raise AppError(
                f"Fetch failed — target unreachable from this deployment ({type(exc).__name__}).",
                code="fetch_error",
            )
        if resp.status_code >= 400:
            raise AppError(f"Fetch failed with HTTP {resp.status_code}.", code="fetch_error")
        ctype = resp.headers.get("content-type", "")
        if ctype and not any(t in ctype for t in ("text/", "application/json", "application/xml")):
            raise ValidationAppError(f"Unsupported content type: {ctype}")
        body = resp.text[: settings.http_fetch_max_bytes]
        text = _strip_html(body) if "html" in ctype else body
        return {
            "url": str(resp.url),
            "status": resp.status_code,
            "content_type": ctype,
            "text": text[:8000],
            "truncated": len(text) > 8000,
        }
