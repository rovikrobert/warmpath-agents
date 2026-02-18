"""Web search and fetch utilities for agents.

Provides:
- web_search(query, max_results=5): Search the web, return results
- web_fetch(url, max_chars=10000): Fetch URL, return text content
- Results cached for CACHE_TTL_HOURS to avoid redundant requests

Uses httpx (already a production dependency) and DuckDuckGo HTML search
(no API key required).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, unquote

import httpx

from agents.shared.config import AGENTS_DIR

logger = logging.getLogger(__name__)

CACHE_DIR = AGENTS_DIR / "shared" / ".web_cache"
CACHE_TTL_HOURS = 24
REQUEST_TIMEOUT = 15  # seconds
USER_AGENT = "WarmPath-Agent/1.0 (research bot)"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _cache_key(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}:{value}".encode()).hexdigest()[:16]


def _read_cache(key: str):
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        cached_at = datetime.fromisoformat(data["cached_at"])
        if cached_at.tzinfo is None:
            cached_at = cached_at.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - cached_at).total_seconds() / 3600
        if age_hours > CACHE_TTL_HOURS:
            return None
        return data["payload"]
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


def _write_cache(key: str, payload) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = {"cached_at": datetime.now(timezone.utc).isoformat(), "payload": payload}
    (CACHE_DIR / f"{key}.json").write_text(json.dumps(data, default=str))


# ---------------------------------------------------------------------------
# Web search
# ---------------------------------------------------------------------------


def web_search(query: str, max_results: int = 5) -> list[SearchResult]:
    """Search DuckDuckGo and return results.

    Returns empty list on network failure (graceful degradation).
    Results are cached for CACHE_TTL_HOURS.
    """
    cache_key = _cache_key("search", f"{query}:{max_results}")
    cached = _read_cache(cache_key)
    if cached is not None:
        return [SearchResult(**r) for r in cached]

    try:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()

        results = _parse_ddg_html(resp.text, max_results)
        _write_cache(cache_key, [asdict(r) for r in results])
        return results
    except Exception as exc:
        logger.warning("Web search failed for '%s': %s", query, exc)
        return []


def _parse_ddg_html(html: str, max_results: int) -> list[SearchResult]:
    """Parse DuckDuckGo HTML lite search results."""
    results: list[SearchResult] = []

    # DuckDuckGo HTML results use class="result__a" for title links
    # and class="result__snippet" for descriptions
    result_blocks = re.findall(
        r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
        r'class="result__snippet"[^>]*>(.*?)</(?:a|span)',
        html,
        re.DOTALL,
    )

    for link_url, title, snippet in result_blocks[:max_results]:
        clean_title = re.sub(r"<[^>]+>", "", title).strip()
        clean_snippet = re.sub(r"<[^>]+>", "", snippet).strip()

        # DuckDuckGo sometimes wraps URLs in a redirect
        if "/l/?uddg=" in link_url:
            url_match = re.search(r"uddg=([^&]+)", link_url)
            if url_match:
                link_url = unquote(url_match.group(1))

        if clean_title:
            results.append(
                SearchResult(title=clean_title, url=link_url, snippet=clean_snippet)
            )

    return results


# ---------------------------------------------------------------------------
# Web fetch
# ---------------------------------------------------------------------------


def web_fetch(url: str, max_chars: int = 10000) -> str:
    """Fetch a URL and return its text content (HTML tags stripped).

    Returns empty string on network failure (graceful degradation).
    Results are cached for CACHE_TTL_HOURS.
    """
    cache_key = _cache_key("fetch", url)
    cached = _read_cache(cache_key)
    if cached is not None:
        return cached

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()

        text = _html_to_text(resp.text)[:max_chars]
        _write_cache(cache_key, text)
        return text
    except Exception as exc:
        logger.warning("Web fetch failed for '%s': %s", url, exc)
        return ""


def _html_to_text(html: str) -> str:
    """Naive HTML to text converter (no external deps)."""
    # Remove script and style blocks
    text = re.sub(
        r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE
    )
    # Replace block elements with newlines
    text = re.sub(
        r"<(?:br|p|div|li|h[1-6])[^>]*/?>", "\n", text, flags=re.IGNORECASE
    )
    # Remove remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode common HTML entities
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
    )
    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
