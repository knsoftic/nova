"""Installed-application catalog: merges Start menu + registry sources and resolves spoken names."""

from __future__ import annotations

import difflib
import re
from typing import Any

from pydantic import BaseModel

from .models import AppEntry

# Spoken/short names (English, Roman Urdu, Urdu, Hindi) -> canonical name prefix of the installed app.
ALIASES: dict[str, list[str]] = {
    "Google Chrome": ["chrome", "google chrome", "کروم", "گوگل کروم", "क्रोम", "गूगल क्रोम"],
    "Visual Studio Code": ["vs code", "vscode", "code", "visual studio code", "وی ایس کوڈ", "वीएस कोड"],
    "WhatsApp": ["whatsapp", "whats app", "watsapp", "واٹس ایپ", "واٹس اپ", "व्हाट्सएप", "वॉट्सऐप"],
    "Adobe Photoshop": ["photoshop", "adobe photoshop", "فوٹوشاپ", "फोटोशॉप"],
    "File Explorer": ["file explorer", "explorer", "files", "my computer", "فائل ایکسپلورر"],
    "Microsoft Edge": ["edge", "microsoft edge", "ایج"],
    "Firefox": ["firefox", "mozilla firefox", "فائر فاکس"],
    "Brave": ["brave", "brave browser"],
    "Notepad": ["notepad", "نوٹ پیڈ", "नोटपैड"],
    "Calculator": ["calculator", "calc", "کیلکولیٹر", "कैलकुलेटर"],
    "Settings": ["settings", "windows settings", "سیٹنگز", "सेटिंग्स"],
    "Task Manager": ["task manager"],
    "Command Prompt": ["cmd", "command prompt"],
    "Windows PowerShell": ["powershell"],
    "Terminal": ["terminal", "windows terminal"],
    "Word": ["word", "ms word", "microsoft word"],
    "Excel": ["excel", "ms excel", "microsoft excel"],
    "PowerPoint": ["powerpoint", "ms powerpoint", "microsoft powerpoint"],
    "Outlook": ["outlook"],
    "Spotify": ["spotify"],
    "Telegram": ["telegram"],
}

_ALIAS_INDEX: dict[str, str] = {}

_JUNK = re.compile(
    r"\b(uninstall|readme|read me|release notes|license|help|website|documentation|manual|support)\b",
    re.IGNORECASE,
)


def normalize(name: str) -> str:
    name = name.lower()
    name = re.sub(r"\(.*?\)", " ", name)  # "(User)", "(x64)"
    name = re.sub(r"\b\d+(\.\d+)+\b", " ", name)  # version numbers
    return re.sub(r"[^\w]+", "", name, flags=re.UNICODE)


for _canonical, _aliases in ALIASES.items():
    for _alias in _aliases:
        _ALIAS_INDEX[normalize(_alias)] = _canonical


def merge_apps(start_apps: list[dict[str, Any]], registry: list[AppEntry], exe_paths: dict[str, str]) -> list[AppEntry]:
    merged: dict[str, AppEntry] = {}

    for raw in start_apps:
        name = (raw.get("Name") or "").strip()
        if not name or _JUNK.search(name):
            continue
        key = normalize(name)
        if key and key not in merged:
            merged[key] = AppEntry(name=name, app_id=raw.get("AppID"), sources=["start_menu"])

    for app in registry:
        key = normalize(app.name)
        if not key:
            continue
        target = merged.get(key) or next(
            (e for k, e in merged.items() if len(k) >= 6 and len(key) >= 6 and (k.endswith(key) or key.endswith(k))),
            None,
        )
        if target:
            target.version = target.version or app.version
            target.publisher = target.publisher or app.publisher
            target.executable = target.executable or app.executable
            target.install_location = target.install_location or app.install_location
            if "registry" not in target.sources:
                target.sources.append("registry")
        elif key not in merged:
            merged[key] = app

    # App Paths gives reliable exe locations (chrome.exe, code.exe...); attach where names line up.
    for exe_name, path in exe_paths.items():
        stem = normalize(exe_name.removesuffix(".exe"))
        for key, entry in merged.items():
            if entry.executable is None and (key == stem or (len(stem) >= 4 and key.endswith(stem))):
                entry.executable = path
                if "app_paths" not in entry.sources:
                    entry.sources.append("app_paths")

    return sorted(merged.values(), key=lambda a: a.name.lower())


class AppMatch(BaseModel):
    app: AppEntry
    score: float
    via_alias: str | None = None


def find_app(apps: list[AppEntry], query: str) -> AppMatch | None:
    q = normalize(query)
    if not q:
        return None

    def rank(entry: AppEntry) -> tuple[int, int]:
        # Prefer launchable Start menu entries, then the shortest name ("WhatsApp" over "WhatsApp Beta").
        return (0 if "start_menu" in entry.sources else 1, len(entry.name))

    canonical = _ALIAS_INDEX.get(q)
    if canonical:
        target = normalize(canonical)
        exact = [a for a in apps if normalize(a.name) == target]
        if exact:
            return AppMatch(app=min(exact, key=rank), score=1.0, via_alias=canonical)
        prefixed = [a for a in apps if normalize(a.name).startswith(target) or normalize(a.name).endswith(target)]
        if prefixed:
            return AppMatch(app=min(prefixed, key=rank), score=0.9, via_alias=canonical)

    exact = [a for a in apps if normalize(a.name) == q]
    if exact:
        return AppMatch(app=min(exact, key=rank), score=1.0)

    if len(q) >= 3:
        contains = [a for a in apps if q in normalize(a.name)]
        if contains:
            return AppMatch(app=min(contains, key=rank), score=0.75)

    names = {normalize(a.name): a for a in apps}
    close = difflib.get_close_matches(q, list(names), n=1, cutoff=0.8)
    if close:
        return AppMatch(app=names[close[0]], score=0.7)
    return None
