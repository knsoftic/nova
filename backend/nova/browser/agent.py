"""Browser Agent: open websites, visible searches, read/summarise pages, scroll/back/forward, and -
with the user's permission - click, fill fields and download files in NOVA's own browser window."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from ..agents.computer import ControlOutcome
from ..ai.base import Intent
from ..research.extract import extract_text
from .controller import BrowserController, ElementInfo, PageState, normalise_url

NAME = "Browser Agent"

# Spoken site names -> address, for "YouTube kholo" when no such app is installed.
KNOWN_SITES = {
    "youtube": "youtube.com", "google": "google.com", "gmail": "mail.google.com", "facebook": "facebook.com",
    "instagram": "instagram.com", "twitter": "x.com", "x": "x.com", "linkedin": "linkedin.com",
    "github": "github.com", "wikipedia": "wikipedia.org", "chatgpt": "chatgpt.com", "netflix": "netflix.com",
    "amazon": "amazon.com", "daraz": "daraz.pk", "google maps": "maps.google.com", "maps": "maps.google.com",
    "whatsapp web": "web.whatsapp.com", "stackoverflow": "stackoverflow.com", "stack overflow": "stackoverflow.com",
    "yahoo": "yahoo.com", "bbc": "bbc.com", "dawn": "dawn.com", "geo news": "geo.tv", "reddit": "reddit.com",
}
# Files that can run code when opened: downloading them is high risk, and NOVA never opens downloads.
EXECUTABLE_EXTENSIONS = {".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".jse", ".scr", ".com", ".pif",
                         ".hta", ".cpl", ".msc", ".jar", ".reg", ".lnk", ".appx", ".msix"}
NAV_LABELS = {"scroll_down": "neeche scroll", "scroll_up": "upar scroll", "back": "pichla page",
              "forward": "agla page", "reload": "page reload"}


def site_for(name: str) -> str | None:
    key = name.lower().strip().removesuffix(" website").removesuffix(" site")
    return KNOWN_SITES.get(key)


def looks_sensitive_field(info: ElementInfo) -> str | None:
    """Fields NOVA must never type into, whatever the user approved."""
    if info.input_type == "password":
        return "Ye password ka khana hai — NOVA password kabhi nahi likhta. Khud likhein."
    marker = f"{info.autocomplete or ''} {info.name or ''} {info.text or ''}".lower()
    if any(k in marker for k in ("cc-number", "cc-csc", "card number", "cardnumber", "cvv", "cvc", "one-time-code", "otp")):
        return "Ye card/OTP ka khana lagta hai — NOVA aisi maloomat nahi likhta. Khud likhein."
    return None


@dataclass
class BrowserTarget:
    title: str | None
    host: str | None
    element: ElementInfo | None = None
    refusal: str | None = None


class BrowserAgent:
    def __init__(self, browser: BrowserController, engine: Callable[[], str]) -> None:
        self.browser = browser
        self.engine = engine

    # ------------------------------------------------------------------ permission support

    def describe_target(self, intent: Intent) -> BrowserTarget:
        """What a risky browser action would touch, resolved before asking the user."""
        state = self.browser.state()
        title, host = (state.title, state.host) if state else (None, None)
        e = intent.entities
        if intent.name == "browser_click" or intent.name == "download":
            if state is None:
                return BrowserTarget(title, host, refusal="NOVA ka browser abhi khula nahi — pehle website kholein.")
            info = self.browser.inspect_click(str(e.get("target") or ""))
            if not info.found:
                return BrowserTarget(title, host, info, refusal=f"Page par \"{e.get('target')}\" nahi mila.")
            return BrowserTarget(title, host, info)
        if intent.name == "browser_type":
            if state is None:
                return BrowserTarget(title, host, refusal="NOVA ka browser abhi khula nahi — pehle website kholein.")
            info = self.browser.inspect_field(e.get("field"))
            if not info.found:
                field = str(e.get("field") or "").strip()
                return BrowserTarget(title, host, info, refusal=f"Page par \"{field}\" wala khana nahi mila."
                                     if field else "Page par likhne ka khana nahi mila.")
            return BrowserTarget(title, host, info, refusal=looks_sensitive_field(info))
        return BrowserTarget(title, host)

    # ------------------------------------------------------------------ actions

    def run(self, intent: Intent, approved: bool = False, element: ElementInfo | None = None) -> ControlOutcome:
        e = intent.entities
        if intent.name in ("browser_click", "browser_type", "download") and not approved:
            raise PermissionError(f"{intent.name} requires the user's permission")
        match intent.name:
            case "open_website":
                return self.open_website(str(e.get("url") or ""))
            case "web_search":
                return self.search(str(e.get("query") or ""))
            case "read_page":
                read = self.page_text()
                return read if isinstance(read, ControlOutcome) else self.page_outcome(*read, summary=None)
            case "browser_nav":
                return self.navigate(str(e.get("action") or "scroll_down"))
            case "browser_click":
                return self.click(str(e.get("target") or ""), element)
            case "browser_type":
                return self.type(e.get("field"), str(e.get("text") or ""))
            case "download":
                return self.download(str(e.get("target") or ""))
        raise ValueError(f"Not a browser intent: {intent.name}")

    def _loaded(self, verb: str, state: PageState, expected_host: str | None) -> ControlOutcome:
        ok = bool(state.url) and (expected_host is None or expected_host.removeprefix("www.") in state.host)
        title = state.title or state.host
        if ok:
            return ControlOutcome(f"{verb}: \"{title}\" khul gaya. (Verify: page {state.host} load hua.)",
                                  "open_website", True, "passed", state.url)
        return ControlOutcome(f"{verb} ki koshish ki, lekin page {state.url} par ruk gaya.", "open_website", True,
                              "failed", state.url)

    def open_website(self, raw: str) -> ControlOutcome:
        if not raw:
            return ControlOutcome("Kaun si website kholni hai?", "open_website", False, "not_applicable")
        if not site_for(raw) and "." not in raw and "localhost" not in raw.lower():
            # A plain name we do not know ("daraz" is known, "xyzabc" is not): search for it instead of guessing.
            return self.search(raw)
        try:
            url = normalise_url(site_for(raw) or raw)
        except ValueError as exc:
            return ControlOutcome(str(exc), "open_website", False, "not_applicable")
        try:
            state = self.browser.goto(url)
        except Exception as exc:
            return ControlOutcome(f"Website nahi khul saki: {type(exc).__name__}. Internet ya address check karein.",
                                  "open_website", False, "failed")
        return self._loaded("Website", state, urlparse(url).hostname)

    def search(self, query: str) -> ControlOutcome:
        if not query:
            return ControlOutcome("Kya search karna hai?", "web_search", False, "not_applicable")
        try:
            state = self.browser.search(query, self.engine())
        except Exception as exc:
            return ControlOutcome(f"Search page nahi khul saka: {type(exc).__name__}.", "web_search", False, "failed")
        if state.url:
            return ControlOutcome(f"NOVA ke browser mein \"{query}\" ki search khol di ({self.engine()}). "
                                  "Results screen par hain.", "web_search", True, "passed", state.url)
        return ControlOutcome("Search page load nahi hua.", "web_search", True, "failed")

    def page_text(self) -> tuple[str, str, str] | ControlOutcome:
        """(title, url, main text) of the open page - or an outcome explaining why there is none.
        Summarising is done by the caller (async, with the local model)."""
        read = self.browser.read()
        if read is None:
            return ControlOutcome("NOVA ka browser abhi khula nahi — pehle koi website kholein.", "read_page", False,
                                  "not_applicable")
        state, html = read
        title, text = extract_text(html, state.url, max_words=900)
        if not text:
            return ControlOutcome(f"\"{state.title}\" page par parhne layak text nahi mila.", "read_page", True,
                                  "not_applicable")
        return title or state.title, state.url, text

    @staticmethod
    def page_outcome(title: str, url: str, text: str, summary: str | None) -> ControlOutcome:
        if summary:
            return ControlOutcome(f"\"{title}\" ka khulasa:\n{summary}", "read_page", True, "not_applicable", url)
        excerpt = " ".join(text.split()[:90])
        return ControlOutcome(f"\"{title}\" par likha hai: {excerpt}...", "read_page", True, "not_applicable", url)

    def navigate(self, action: str) -> ControlOutcome:
        if self.browser.state() is None:
            return ControlOutcome("NOVA ka browser abhi khula nahi.", f"browser_{action}", False, "not_applicable")
        state, changed = self.browser.navigate(action)
        label = NAV_LABELS.get(action, action)
        if changed:
            return ControlOutcome(f"{label} kar diya.", f"browser_{action}", True, "passed", state.url)
        return ControlOutcome(f"{label} kiya, lekin page wahi raha (shayad page ka aakhir/shuru hai).",
                              f"browser_{action}", True, "failed", state.url)

    def click(self, label: str, approved_element: ElementInfo | None) -> ControlOutcome:
        expected = approved_element.text if approved_element else label
        status, state = self.browser.click(label, expected)
        if status == "not_found":
            return ControlOutcome(f"Page par \"{label}\" nahi mila, is liye click nahi kiya.", "browser_click", False,
                                  "failed")
        if status == "changed_target":
            return ControlOutcome("Page badal gaya hai aur ab wahi cheez nahi mil rahi jiski ijazat di thi — click "
                                  "nahi kiya. Dobara kahein.", "browser_click", False, "failed")
        if status == "clicked_changed" and state:
            return ControlOutcome(f"\"{expected}\" par click kar diya. (Verify: page badla — {state.title or state.host}.)",
                                  "browser_click", True, "passed", state.url)
        return ControlOutcome(f"\"{expected}\" par click kar diya, lekin page mein koi wazeh tabdeeli nazar nahi aayi.",
                              "browser_click", True, "unverified")

    def type(self, field: object, text: str) -> ControlOutcome:
        if not text:
            return ControlOutcome("Kya likhna hai?", "browser_type", False, "not_applicable")
        status, value = self.browser.fill(str(field) if field else None, text)
        if status == "not_found":
            return ControlOutcome("Page par likhne ka khana nahi mila.", "browser_type", False, "failed")
        if status == "refused_password":
            return ControlOutcome("Ye password ka khana hai — NOVA password kabhi nahi likhta.", "browser_type", False,
                                  "not_applicable")
        if value == text:
            return ControlOutcome(f"Likh diya: \"{text[:60]}\". (Verify: khane mein wahi text hai.)", "browser_type",
                                  True, "passed")
        return ControlOutcome(f"Likh diya: \"{text[:60]}\", lekin khane ki value tasdeeq nahi hui.", "browser_type", True,
                              "unverified")

    def download(self, label: str) -> ControlOutcome:
        status, path = self.browser.download(label)
        if status == "not_found":
            return ControlOutcome(f"Page par \"{label}\" nahi mila.", "download", False, "failed")
        if status == "not_a_download" or path is None:
            return ControlOutcome(f"\"{label}\" par click se koi file download nahi hui.", "download", False, "failed")
        size = path.stat().st_size if path.exists() else 0
        if size <= 0:
            return ControlOutcome("File download hui lekin khaali hai.", "download", True, "failed", str(path))
        warn = " Ye program/script file hai — NOVA ise nahi kholega; sirf bharosemand source ho to khud kholein." \
            if path.suffix.lower() in EXECUTABLE_EXTENSIONS else ""
        return ControlOutcome(f"File download ho gayi: {path} ({size // 1024} KB). (Verify: file mojood hai.){warn}",
                              "download", True, "passed", str(path))


def download_is_executable(label: str, element: ElementInfo | None) -> bool:
    hint = f"{label} {element.href if element and element.href else ''}".lower().split("?")[0]
    return any(hint.endswith(ext) or f"{ext} " in hint + " " for ext in EXECUTABLE_EXTENSIONS)


__all__ = ["NAME", "BrowserAgent", "BrowserTarget", "KNOWN_SITES", "download_is_executable", "site_for"]
