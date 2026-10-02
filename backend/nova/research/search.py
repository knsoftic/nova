"""Web search through official APIs only (never scraping search-engine result pages).

- Brave Search API: general web search; needs the user's own API key (free tier available).
- Wikipedia API: no key; encyclopedic knowledge only. Used when no Brave key is configured.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

import httpx

from .netsafe import USER_AGENT

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
WIKI_API = "https://en.wikipedia.org/w/api.php"
TIMEOUT_S = 15.0


class SearchError(RuntimeError):
    """A provider failed in a way the user should hear about (bad key, quota, offline)."""


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    extra: list[str] = field(default_factory=list)
    age: str | None = None


def _clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(text or ""))).strip()


# Roman Urdu grammar words. English Wikipedia matches them against unrelated articles
# ("dollar ka rate kya hai" found film pages), so only the content words are searched.
_FILLER = set("""
ka ki ke ko kya hai hain tha thi the mein me se par pe aur ya baare bare kaisa kaisi kaise kaun kab kahan kitna
kitni kitne aaj kal abhi bhi to jo wo woh ye yeh is us un in liye wala wali wale batao bataen bataiye
""".split())


def search_terms(query: str) -> str:
    words = query.split()
    kept = [w for w in words if w.lower().strip("?.,!") not in _FILLER]
    return " ".join(kept) or query


class BraveSearch:
    name = "brave"
    label = "Brave Search"

    def __init__(self, api_key: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._key = api_key
        self._transport = transport

    async def search(self, query: str, count: int = 6) -> list[SearchResult]:
        headers = {"Accept": "application/json", "X-Subscription-Token": self._key, "User-Agent": USER_AGENT}
        params = {"q": query[:400], "count": max(1, min(count, 20)), "safesearch": "moderate", "text_decorations": "false"}
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT_S) as client:
                r = await client.get(BRAVE_URL, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise SearchError("Brave Search se rabta nahi ho saka (internet check karein)") from exc
        if r.status_code in (401, 403):
            raise SearchError("Brave API key sahi nahi lag rahi — Settings mein check karein")
        if r.status_code == 429:
            raise SearchError("Brave Search ki had (quota) poori ho gayi — thori der baad koshish karein")
        if r.status_code >= 400:
            raise SearchError(f"Brave Search ne error diya ({r.status_code})")
        results = []
        for item in (r.json().get("web") or {}).get("results", [])[:count]:
            if not item.get("url", "").startswith(("http://", "https://")):
                continue
            results.append(SearchResult(title=_clean(item.get("title")), url=item["url"],
                                        snippet=_clean(item.get("description")),
                                        extra=[_clean(s) for s in item.get("extra_snippets", [])[:3]],
                                        age=item.get("age")))
        return results


class WikipediaSearch:
    name = "wikipedia"
    label = "Wikipedia"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def search(self, query: str, count: int = 4) -> list[SearchResult]:
        params = {"action": "query", "list": "search", "srsearch": search_terms(query)[:300], "srlimit": max(1, min(count, 10)),
                  "format": "json", "utf8": 1}
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=TIMEOUT_S,
                                         headers={"User-Agent": USER_AGENT}) as client:
                r = await client.get(WIKI_API, params=params)
                r.raise_for_status()
                hits = r.json().get("query", {}).get("search", [])
                if not hits:
                    return []
                titles = "|".join(h["title"] for h in hits[:count])
                ex = await client.get(WIKI_API, params={"action": "query", "prop": "extracts", "exintro": 1,
                                                        "explaintext": 1, "titles": titles, "format": "json",
                                                        "redirects": 1})
                ex.raise_for_status()
                pages = ex.json().get("query", {}).get("pages", {})
        except httpx.HTTPError as exc:
            raise SearchError("Wikipedia se rabta nahi ho saka (internet check karein)") from exc
        intros = {p.get("title"): p.get("extract", "") for p in pages.values()}
        results = []
        for h in hits[:count]:
            title = h["title"]
            intro = _clean(intros.get(title)) or _clean(h.get("snippet"))
            if "(disambiguation)" in title or intro.rstrip().endswith("may refer to:"):
                continue  # a list of other articles, not a source
            results.append(SearchResult(title=title, url="https://en.wikipedia.org/wiki/" + title.replace(" ", "_"),
                                        snippet=intro[:600], extra=[intro[600:1800]] if len(intro) > 600 else []))
        return results
