"""Workflow memory: named routines ("work", "study") that open apps, websites, code projects and folders.

The user's words ("Chrome, VS Code, github.com aur nova project") are resolved once, when the workflow is saved,
into exact steps - so "work start karo" later does exactly what the user saw and approved. Only "open" steps
(and a fixed volume/brightness level) are allowed: nothing that deletes, sends or changes the user's files.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from ..ai.base import Intent
from ..discovery.apps import find_app
from ..discovery.models import AppEntry

MAX_STEPS = 10
MAX_NAME_CHARS = 30
NAME_ALIASES = {"kaam": "work", "work environment": "work", "mera kaam": "work", "office work": "work"}
KINDS = ("app", "website", "project", "folder", "setting")

STEP_SPLIT = re.compile(r"\s*(?:,|،|;|\+|\n|\b(?:aur\s+phir|aur|and\s+then|and|phir|then)\b|\s(?:اور|और)\s)\s*",
                        re.IGNORECASE)
STEP_VERB = re.compile(r"\s+(?:kholo|khol\s+do|khulein|open\s+karo|open\s+kar\s+do|chalao|chala\s+do|start\s+karo|"
                       r"launch\s+karo|bhi)$|^(?:open|launch|start|run)\s+", re.IGNORECASE)
STEP_FILLER = re.compile(r"^(?:mera|meri|mere|my|the|apna|apni)\s+|\s+(?:app|application)$", re.IGNORECASE)
WEBSITE = re.compile(r"^(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?::\d+)?(?:/\S*)?$", re.IGNORECASE)
SETTING_STEP = re.compile(r"^(?:(?P<vol>volume|awaaz|awaz|aawaz)|(?P<bri>brightness|roshni))\s+(?:ko\s+)?(?P<n>\d{1,3})"
                          r"\s*%?$|^(?P<mute>mute)$|^(?:volume\s+)?(?P<unmute>unmute)$", re.IGNORECASE)
KNOWN_FOLDER_WORDS = re.compile(r"^(?:desktop|documents?|downloads?|pictures?|music|videos?)$", re.IGNORECASE)
FOLDER_STEP = re.compile(r"^(?P<f>.+?)\s+(?:wala\s+|wali\s+)?folder$", re.IGNORECASE)
PROJECT_STEP = re.compile(r"^(?P<p>.+?)\s+project$", re.IGNORECASE)


@dataclass
class WorkflowStep:
    kind: str  # app | website | project | folder | setting
    value: str  # app name, URL/site, project name, folder path, or level
    label: str  # shown to the user
    setting: str | None = None  # volume | brightness | mute | unmute (kind "setting")

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WorkflowStep":
        return cls(str(d["kind"]), str(d["value"]), str(d.get("label") or d["value"]), d.get("setting"))

    def intent(self, language: str = "unknown") -> Intent:
        """The exact command this step runs - through the normal plan, permission and verification."""
        name, entities = {
            "app": ("open_app", {"app": self.value}),
            "website": ("open_website", {"url": self.value}),
            "project": ("open_project", {"project": self.value}),
            "folder": ("open_file", {"target": self.value}),
            "setting": ("change_setting", {"setting": self.setting, "value": self.value}),
        }[self.kind]
        return Intent(name=name, confidence=1.0, language=language, entities=entities, provider="memory")

    def describe(self) -> str:
        what = {"app": "app", "website": "website", "project": "project", "folder": "folder", "setting": "setting"}
        return f"{self.label} ({what[self.kind]})"


def workflow_key(name: str) -> str:
    """"Work Environment" -> "work"; "study workflow" -> "study"."""
    key = " ".join(re.sub(r"[\"'“”‘’]", " ", str(name or "")).lower().split())
    key = re.sub(r"\s+(?:workflow|routine)$", "", key).strip()
    return NAME_ALIASES.get(key, key)[:MAX_NAME_CHARS]


def split_items(text: str) -> list[str]:
    items = []
    for part in STEP_SPLIT.split(str(text or "")):
        item = " ".join(part.split()).strip(" .!?۔\"'“”")
        for _ in range(2):  # "Chrome bhi kholo", "open my VS Code app"
            item = STEP_FILLER.sub("", STEP_VERB.sub("", item)).strip()
        if item:
            items.append(item)
    return items


class StepResolver:
    """Turns the user's words into exact steps, using what is really on this PC."""

    def __init__(
        self,
        apps: Callable[[], list[AppEntry] | None],
        projects: Callable[[str], Path | list[str] | None],
        folder: Callable[[str], Any],  # Path, or a Reply explaining why not
        site_for: Callable[[str], str | None],
    ) -> None:
        self.apps = apps
        self.projects = projects
        self.folder = folder
        self.site_for = site_for

    def resolve(self, item: str) -> WorkflowStep | str:
        """The step for one item, or why it cannot be used (Roman Urdu)."""
        t = item.strip()
        if m := SETTING_STEP.match(t):
            if m["mute"]:
                return WorkflowStep("setting", "", "Awaaz band (mute)", "mute")
            if m["unmute"]:
                return WorkflowStep("setting", "", "Awaaz chalu (unmute)", "unmute")
            level = min(int(m["n"]), 100)
            setting = "volume" if m["vol"] else "brightness"
            return WorkflowStep("setting", str(level), f"{setting.capitalize()} {level}%", setting)
        if m := PROJECT_STEP.match(t):
            found = self.projects(m["p"])
            if isinstance(found, Path):
                return WorkflowStep("project", found.name, f"{found.name} project")
            if isinstance(found, list):
                return f"\"{m['p']}\" se kai projects milte hain ({', '.join(found[:4])}) — poora naam batayein"
            return f"\"{m['p']}\" naam ka project nahi mila"
        folder_name = FOLDER_STEP.match(t)
        if folder_name or KNOWN_FOLDER_WORDS.match(t) or re.match(r"^[a-z]:\\", t, re.IGNORECASE):
            found = self.folder(folder_name["f"] if folder_name else t)
            if isinstance(found, Path):
                return WorkflowStep("folder", str(found), found.name)
            return getattr(found, "message", f"\"{t}\" folder nahi mila").rstrip(".")
        if WEBSITE.match(t):
            return WorkflowStep("website", t.lower(), t.lower())
        apps = self.apps()
        match = find_app(apps, t) if apps else None
        if match is not None:
            return WorkflowStep("app", match.app.name, match.app.name)
        if site := self.site_for(t):
            return WorkflowStep("website", site, t if t[:1].isupper() else t.capitalize())
        return f"\"{t}\" na is PC par app mili, na website/project/folder"

    def resolve_all(self, text: str) -> tuple[list[WorkflowStep], list[str]]:
        steps: list[WorkflowStep] = []
        problems: list[str] = []
        for item in split_items(text):
            found = self.resolve(item)
            if isinstance(found, str):
                problems.append(found)
            elif not any(s.kind == found.kind and s.value == found.value for s in steps):
                steps.append(found)
        return steps, problems


def merge(current: list[WorkflowStep], change: list[WorkflowStep], action: str) -> list[WorkflowStep]:
    if action == "add":
        out = list(current)
        for step in change:
            if not any(s.kind == step.kind and s.value == step.value for s in out):
                out.append(step)
        return out
    if action == "remove":
        gone = {(s.kind, s.value) for s in change}
        return [s for s in current if (s.kind, s.value) not in gone]
    return list(change)


def numbered(steps: list[WorkflowStep]) -> str:
    return "\n".join(f"{n}. {s.describe()}" for n, s in enumerate(steps, start=1))
