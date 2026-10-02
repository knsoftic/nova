"""Find files and folders by name or type inside the allowed folders.

The walk is breadth-first (shallow, likely matches first) and bounded by depth, entry count and time,
and it skips heavy generated folders (node_modules, .git, vendor, virtualenvs...).
"""

from __future__ import annotations

import os
import re
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = frozenset({
    "node_modules", ".git", ".svn", ".hg", "vendor", "__pycache__", ".venv", "venv", "env", ".idea", ".vs",
    ".vscode", "dist", "build", ".next", ".nuxt", ".cache", ".pytest_cache", ".mypy_cache", ".gradle",
    "$recycle.bin", "system volume information", "appdata",
})

# Spoken type names -> extensions ("pdf files dhoondo", "tasveerein dikhao").
TYPE_WORDS: dict[str, tuple[str, ...]] = {
    "pdf": (".pdf",), "pdfs": (".pdf",),
    "word": (".doc", ".docx"), "docx": (".docx",), "doc": (".doc", ".docx"),
    "excel": (".xls", ".xlsx", ".csv"), "xlsx": (".xlsx",), "csv": (".csv",), "spreadsheet": (".xls", ".xlsx", ".csv"),
    "powerpoint": (".ppt", ".pptx"), "ppt": (".ppt", ".pptx"), "slides": (".ppt", ".pptx"),
    "text": (".txt",), "txt": (".txt",),
    "image": (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic"), "images": (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic"),
    "photo": (".jpg", ".jpeg", ".png", ".heic"), "photos": (".jpg", ".jpeg", ".png", ".heic"),
    "tasveer": (".jpg", ".jpeg", ".png", ".heic"), "tasveerein": (".jpg", ".jpeg", ".png", ".heic"),
    "jpg": (".jpg", ".jpeg"), "png": (".png",),
    "video": (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"), "videos": (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm"),
    "mp4": (".mp4",), "audio": (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"), "mp3": (".mp3",),
    "songs": (".mp3", ".wav", ".m4a"), "gaane": (".mp3", ".wav", ".m4a"),
    "zip": (".zip", ".rar", ".7z"), "zips": (".zip", ".rar", ".7z"),
    "python": (".py",), "php": (".php",), "javascript": (".js", ".jsx", ".mjs"), "html": (".html", ".htm"),
}


@dataclass
class Hit:
    path: Path
    is_dir: bool
    size: int
    modified: float
    score: int


@dataclass
class SearchResult:
    hits: list[Hit]
    truncated: bool  # the time/entry budget ran out before every folder was searched
    searched: int


def _tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", text.lower())


def query_types(query: str) -> tuple[str, tuple[str, ...] | None]:
    """Split "pdf report" into a name part ("report") and a type filter ((".pdf",))."""
    words = query.lower().split()
    exts: list[str] = []
    rest = []
    for w in words:
        clean = w.strip(".")
        if clean in TYPE_WORDS:
            exts.extend(TYPE_WORDS[clean])
        elif w.startswith("*.") or (w.startswith(".") and len(w) <= 6):
            exts.append("." + w.lstrip("*."))
        else:
            rest.append(w)
    return " ".join(rest), (tuple(dict.fromkeys(exts)) or None)


def _score(name: str, query: str, tokens: list[str]) -> int:
    lower = name.lower()
    stem = lower.rsplit(".", 1)[0] if "." in lower[1:] else lower
    if not query:
        return 40
    if lower == query:
        return 100
    if stem == query:
        return 90
    if lower.startswith(query):
        return 70
    if query in lower:
        return 60
    if tokens and all(t in lower for t in tokens):
        return 50
    return 0


def search(
    roots: list[Path],
    query: str = "",
    exts: tuple[str, ...] | None = None,
    *,
    want_dirs: bool | None = None,  # True: folders only, False: files only, None: both
    limit: int = 10,
    budget_s: float = 4.0,
    max_depth: int = 7,
    max_entries: int = 80_000,
    exclude_dirs: frozenset[str] = frozenset(),  # normcased paths never entered (NOVA's private data)
    hide: re.Pattern[str] | None = None,  # names never returned (secret files)
) -> SearchResult:
    query = query.strip().lower()
    tokens = _tokens(query)
    deadline = time.monotonic() + budget_s
    queue: deque[tuple[Path, int]] = deque((r, 0) for r in roots)
    seen_dirs: set[str] = set()
    hits: list[Hit] = []
    searched = 0
    truncated = False
    while queue:
        folder, depth = queue.popleft()
        key = os.path.normcase(str(folder))
        if key in seen_dirs:
            continue
        seen_dirs.add(key)
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            searched += 1
            if searched > max_entries or time.monotonic() > deadline:
                truncated = True
                queue.clear()
                break
            name = entry.name
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if is_dir and os.path.normcase(entry.path) in exclude_dirs:
                continue
            if hide is not None and hide.search(name):
                continue
            if is_dir and depth < max_depth and name.lower() not in SKIP_DIRS and not name.startswith("."):
                queue.append((Path(entry.path), depth + 1))
            if (want_dirs is True and not is_dir) or (want_dirs is False and is_dir):
                continue
            if exts and (is_dir or not name.lower().endswith(exts)):
                continue
            score = _score(name, query, tokens)
            if score:
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                hits.append(Hit(Path(entry.path), is_dir, 0 if is_dir else st.st_size, st.st_mtime, score))
    hits.sort(key=lambda h: (-h.score, -h.modified))
    return SearchResult(hits[:limit], truncated, searched)
