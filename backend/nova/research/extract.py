"""Main readable text of an HTML page (article body, without menus/ads)."""

from __future__ import annotations

import re

MAX_WORDS = 1200


def extract_text(html: str, url: str | None = None, max_words: int = MAX_WORDS) -> tuple[str | None, str]:
    """Returns (title, text). Uses trafilatura; falls back to stripping tags if it finds nothing."""
    title = None
    text = ""
    try:
        import trafilatura

        text = trafilatura.extract(html, url=url, include_comments=False, include_tables=False,
                                   favor_precision=True) or ""
        meta = trafilatura.extract_metadata(html, default_url=url)
        title = meta.title if meta else None
    except Exception:
        text = ""
    if not text.strip():
        text = re.sub(r"(?is)<(script|style|noscript|nav|footer|header)[^>]*>.*?</\1>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
    if title is None and (m := re.search(r"(?is)<title[^>]*>(.*?)</title>", html)):
        title = re.sub(r"\s+", " ", m.group(1)).strip() or None
    words = re.sub(r"[ \t]+", " ", text).split(" ")
    clipped = " ".join(words[:max_words])
    return title, re.sub(r"\n{3,}", "\n\n", clipped).strip()
