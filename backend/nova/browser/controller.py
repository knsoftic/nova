"""NOVA's own browser window, driven with Playwright.

- Uses the installed Chrome (or Edge) with a separate NOVA profile in data/browser-profile, so the
  user's own logged-in browser is never touched. The window is visible: the user sees everything.
- Playwright's sync API runs on one dedicated thread; every call is marshalled there.
- Downloads go to Downloads\\NOVA and are never opened or executed.
"""

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus, urlparse

import psutil

log = logging.getLogger("nova.browser")

SEARCH_URLS = {
    "google": "https://www.google.com/search?q={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
}
CALL_TIMEOUT_S = 90
NAV_TIMEOUT_MS = 30_000


@dataclass
class PageState:
    title: str
    url: str

    @property
    def host(self) -> str:
        return urlparse(self.url).hostname or ""


@dataclass
class ElementInfo:
    found: bool
    text: str = ""  # what the user would read on it (accessible name / visible text)
    kind: str = ""  # link | button | text
    href: str | None = None
    input_type: str | None = None  # for fields: text, search, email, password, ...
    autocomplete: str | None = None
    name: str | None = None


def normalise_url(raw: str) -> str:
    url = raw.strip().strip("\"'")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.IGNORECASE):
        url = "https://" + url
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("Sirf http/https websites khul sakti hain")
    return url


class BrowserController:
    def __init__(self, profile_dir: Path, downloads_dir: Callable[[], Path], channel: Callable[[], str]) -> None:
        self.profile_dir = profile_dir
        self.downloads_dir = downloads_dir
        self.channel = channel
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nova-browser")
        self._pw: Any = None
        self._ctx: Any = None
        self._pid: int | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ thread marshalling

    def _call(self, fn: Callable[..., Any], *args: Any) -> Any:
        return self._executor.submit(fn, *args).result(timeout=CALL_TIMEOUT_S)

    def shutdown(self) -> None:
        try:
            self._call(self._close)
        except Exception:
            pass
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ lifecycle (browser thread only)

    def _alive(self) -> bool:
        try:
            return self._ctx is not None and bool(self._ctx.pages)
        except Exception:
            return False

    def _ensure(self) -> Any:
        if not self._alive():
            self._close()
            from playwright.sync_api import sync_playwright

            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._pw = sync_playwright().start()
            self._ctx = self._pw.chromium.launch_persistent_context(
                str(self.profile_dir), channel=self.channel(), headless=False, no_viewport=True,
                accept_downloads=True, args=["--no-first-run", "--no-default-browser-check"])
            self._ctx.set_default_navigation_timeout(NAV_TIMEOUT_MS)
            self._pid = None
        pages = [p for p in self._ctx.pages if not p.is_closed()]
        return pages[-1] if pages else self._ctx.new_page()

    def _close(self) -> None:
        try:
            if self._ctx is not None:
                self._ctx.close()
        except Exception:
            pass  # the user may already have closed the window
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass
        self._ctx = self._pw = None
        self._pid = None

    # ------------------------------------------------------------------ public API (any thread)

    def is_open(self) -> bool:
        return self._call(self._alive)

    def pid(self) -> int | None:
        """PID of NOVA's browser main process (to recognise its window among the user's windows)."""
        if self._pid and psutil.pid_exists(self._pid):
            return self._pid
        marker = str(self.profile_dir).lower()
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                cmd = proc.info["cmdline"] or []
                if any(marker in a.lower() for a in cmd) and not any(a.startswith("--type=") for a in cmd):
                    self._pid = proc.pid
                    return proc.pid
            except (psutil.Error, TypeError):
                continue
        return None

    def state(self) -> PageState | None:
        def run() -> PageState | None:
            if not self._alive():
                return None
            page = self._ensure()
            return PageState(page.title(), page.url)
        return self._call(run)

    def goto(self, url: str) -> PageState:
        def run() -> PageState:
            page = self._ensure()
            page.goto(url, wait_until="domcontentloaded")
            page.bring_to_front()
            return PageState(page.title(), page.url)
        return self._call(run)

    def search(self, query: str, engine: str) -> PageState:
        return self.goto(SEARCH_URLS.get(engine, SEARCH_URLS["google"]).format(q=quote_plus(query)))

    def read(self) -> tuple[PageState, str] | None:
        def run() -> tuple[PageState, str] | None:
            if not self._alive():
                return None
            page = self._ensure()
            return PageState(page.title(), page.url), page.content()
        return self._call(run)

    def navigate(self, action: str) -> tuple[PageState, bool]:
        """scroll_down | scroll_up | back | forward | reload. Returns (state, changed)."""
        def run() -> tuple[PageState, bool]:
            page = self._ensure()
            before = (page.url, page.evaluate("window.scrollY"))
            if action in ("scroll_down", "scroll_up"):
                page.mouse.wheel(0, 700 if action == "scroll_down" else -700)
                page.wait_for_timeout(400)
            elif action == "back":
                page.go_back(wait_until="domcontentloaded")
            elif action == "forward":
                page.go_forward(wait_until="domcontentloaded")
            elif action == "reload":
                page.reload(wait_until="domcontentloaded")
            after = (page.url, page.evaluate("window.scrollY"))
            return PageState(page.title(), page.url), after != before or action == "reload"
        return self._call(run)

    # ------------------------------------------------------------------ elements

    @staticmethod
    def _locate_clickable(page: Any, label: str) -> tuple[Any, str] | None:
        for kind, loc in (("link", page.get_by_role("link", name=label)),
                          ("button", page.get_by_role("button", name=label)),
                          ("text", page.get_by_text(label))):
            try:
                for i in range(min(loc.count(), 5)):
                    el = loc.nth(i)
                    if el.is_visible():
                        return el, kind
            except Exception:
                continue
        return None

    @staticmethod
    def _locate_field(page: Any, label: str | None) -> Any | None:
        if not label:
            focused = page.locator(":focus")
            if focused.count() and focused.first.evaluate("e => ['INPUT','TEXTAREA'].includes(e.tagName) || e.isContentEditable"):
                return focused.first
            loc = page.locator("input:not([type=hidden]):not([type=submit]):not([type=button]), textarea")
        else:
            # "search box" -> also "search": pages label the field itself ("Search Wikipedia"), not the box.
            names = list(dict.fromkeys([label, re.sub(r"\s+(?:box|field|khana|khane|bar)$", "", label, flags=re.I)]))
            candidates = [loc for n in names for loc in (
                page.get_by_label(n), page.get_by_placeholder(n),
                page.get_by_role("textbox", name=n), page.get_by_role("searchbox", name=n))]
            if "search" in label.lower():
                candidates += [page.get_by_role("searchbox"), page.locator("input[type=search]")]
            for loc in candidates:
                try:
                    if loc.count() and loc.first.is_visible():
                        return loc.first
                except Exception:
                    continue
            return None
        for i in range(min(loc.count(), 10)):
            if loc.nth(i).is_visible():
                return loc.nth(i)
        return None

    def inspect_click(self, label: str) -> ElementInfo:
        def run() -> ElementInfo:
            if not self._alive():
                return ElementInfo(False)
            found = self._locate_clickable(self._ensure(), label)
            if not found:
                return ElementInfo(False)
            el, kind = found
            text = (el.get_attribute("aria-label") or el.inner_text() or label).strip()
            return ElementInfo(True, re.sub(r"\s+", " ", text)[:120], kind, el.get_attribute("href"))
        return self._call(run)

    def inspect_field(self, label: str | None) -> ElementInfo:
        def run() -> ElementInfo:
            if not self._alive():
                return ElementInfo(False)
            el = self._locate_field(self._ensure(), label)
            if el is None:
                return ElementInfo(False)
            return ElementInfo(True, (el.get_attribute("aria-label") or el.get_attribute("placeholder")
                                      or el.get_attribute("name") or label or "")[:80], "field",
                               input_type=(el.get_attribute("type") or "text").lower(),
                               autocomplete=(el.get_attribute("autocomplete") or "").lower(),
                               name=(el.get_attribute("name") or "").lower())
        return self._call(run)

    def click(self, label: str, expected_text: str) -> tuple[str, PageState | None]:
        """Returns (status, state): clicked_changed | clicked_same | not_found | changed_target."""
        def run() -> tuple[str, PageState | None]:
            page = self._ensure()
            found = self._locate_clickable(page, label)
            if not found:
                return "not_found", None
            el, _ = found
            text = re.sub(r"\s+", " ", (el.get_attribute("aria-label") or el.inner_text() or label).strip())[:120]
            if text != expected_text:
                return "changed_target", None  # the page changed since the user approved this exact element
            before = (page.url, page.title(), len(self._ctx.pages))
            el.click(timeout=10_000)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5_000)
            except Exception:
                pass
            page.wait_for_timeout(500)
            pages = [p for p in self._ctx.pages if not p.is_closed()]
            current = pages[-1] if pages else page
            after = (current.url, current.title(), len(pages))
            return ("clicked_changed" if after != before else "clicked_same"), PageState(current.title(), current.url)
        return self._call(run)

    def fill(self, label: str | None, text: str) -> tuple[str, str | None]:
        """Returns (status, value_after): filled | not_found | refused_password."""
        def run() -> tuple[str, str | None]:
            page = self._ensure()
            el = self._locate_field(page, label)
            if el is None:
                return "not_found", None
            if (el.get_attribute("type") or "").lower() == "password":
                return "refused_password", None
            el.fill(text, timeout=10_000)
            try:
                return "filled", el.input_value()
            except Exception:
                return "filled", None
        return self._call(run)

    def download(self, label: str) -> tuple[str, Path | None]:
        """Click a link that downloads a file. Returns (status, saved_path): saved | not_found | not_a_download."""
        def run() -> tuple[str, Path | None]:
            page = self._ensure()
            found = self._locate_clickable(page, label)
            if not found:
                return "not_found", None
            el, _ = found
            try:
                with page.expect_download(timeout=30_000) as info:
                    el.click()
                dl = info.value
            except Exception:
                return "not_a_download", None
            folder = self.downloads_dir()
            folder.mkdir(parents=True, exist_ok=True)
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", dl.suggested_filename or "download")[:150] or "download"
            target = folder / name
            n = 1
            while target.exists():
                target = folder / f"{Path(name).stem} ({n}){Path(name).suffix}"
                n += 1
            dl.save_as(str(target))
            return "saved", target
        return self._call(run)
