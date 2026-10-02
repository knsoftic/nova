"""User behavior patterns: which apps, websites and code projects the user opens, and when.

Kept on this PC like the conversation history (same number of days, deleted with it), visible and deletable in the
Memory tab, and switchable off. When the same things are opened together on several days, NOVA offers to make them
a workflow - and only saves it if the user says yes.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import combinations
from statistics import median
from typing import Any, Iterable

# What a step opened (intent -> kind). Only things a workflow can open again.
OPEN_KINDS = {"open_app": "app", "open_website": "website", "open_project": "project"}
SESSION_GAP_MIN = 10  # things opened within this many minutes of each other belong together
ROUTINE_DAYS = 3  # ... on at least this many different days
LOOKBACK_DAYS = 30
MAX_ITEMS = 6


@dataclass(frozen=True)
class Routine:
    items: tuple[tuple[str, str], ...]  # (kind, target), in the usual order
    days: int
    hour: int  # usual hour of day

    @property
    def key(self) -> str:
        return "|".join(sorted(f"{k}:{t.lower()}" for k, t in self.items))

    @property
    def labels(self) -> list[str]:
        return [f"{t} project" if k == "project" else t for k, t in self.items]

    @property
    def name(self) -> str:
        return part_of_day(self.hour)


def part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "subah"
    if 12 <= hour < 17:
        return "dopahar"
    if 17 <= hour < 21:
        return "shaam"
    return "raat"


def _parse(events: Iterable[dict[str, Any]]) -> list[tuple[datetime, str, str]]:
    out = []
    for e in events:
        try:
            out.append((datetime.fromisoformat(e["created_at"]), e["kind"], e["target"]))
        except (KeyError, ValueError):
            continue
    return sorted(out)


def sessions(events: Iterable[dict[str, Any]], gap_min: int = SESSION_GAP_MIN) -> list[list[tuple[datetime, str, str]]]:
    groups: list[list[tuple[datetime, str, str]]] = []
    for item in _parse(e for e in events if e["kind"] in OPEN_KINDS.values()):
        if groups and item[0] - groups[-1][-1][0] <= timedelta(minutes=gap_min):
            groups[-1].append(item)
        else:
            groups.append([item])
    return groups


def find_routines(events: list[dict[str, Any]], now: datetime, covered: list[set[tuple[str, str]]] | None = None,
                  declined: set[str] | None = None, min_days: int = ROUTINE_DAYS) -> list[Routine]:
    """Sets of 2+ things opened together on `min_days`+ different days (last 30 days), biggest first.
    Sets already inside a saved workflow, or that the user said "nahi" to, are left out."""
    since = now - timedelta(days=LOOKBACK_DAYS)
    days: dict[frozenset[tuple[str, str]], set[str]] = {}
    hours: dict[frozenset[tuple[str, str]], list[int]] = {}
    order: dict[tuple[str, str], list[float]] = {}
    for group in sessions(events):
        if group[0][0] < since:
            continue
        seen: dict[tuple[str, str], int] = {}
        for pos, (_, kind, target) in enumerate(group):
            seen.setdefault((kind, target), pos)
        items = sorted(seen, key=seen.get)[:MAX_ITEMS]
        for item in items:
            order.setdefault(item, []).append(seen[item])
        for size in range(2, len(items) + 1):
            for combo in combinations(items, size):
                key = frozenset(combo)
                days.setdefault(key, set()).add(group[0][0].date().isoformat())
                hours.setdefault(key, []).append(group[0][0].hour)
    covered = covered or []
    # "Nahi" to a routine also covers its smaller parts: NOVA does not keep asking about pieces of it.
    refused = [set(k.split("|")) for k in (declined or set())]
    found: list[Routine] = []
    for key, on_days in sorted(days.items(), key=lambda kv: (len(kv[0]), len(kv[1])), reverse=True):
        if len(on_days) < min_days or any(key <= c for c in covered):
            continue
        if any(key <= set(r.items) for r in found):
            continue  # a bigger routine already contains it
        ordered = tuple(sorted(key, key=lambda i: median(order[i])))
        routine = Routine(ordered, len(on_days), int(median(hours[key])))
        if not any(set(routine.key.split("|")) <= r for r in refused):
            found.append(routine)
    return found


def summary(events: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Most used things and commands with their usual time - for the Memory tab and "meri aadatein batao"."""
    since = now - timedelta(days=LOOKBACK_DAYS)
    parsed = [e for e in _parse(events) if e[0] >= since]
    opened: dict[tuple[str, str], list[datetime]] = {}
    commands: Counter[str] = Counter()
    for when, kind, target in parsed:
        if kind == "command":
            commands[target] += 1
        else:
            opened.setdefault((kind, target), []).append(when)
    top = sorted(opened.items(), key=lambda kv: len(kv[1]), reverse=True)[:10]
    return {
        "items": [{"kind": k, "target": t, "count": len(ts), "days": len({x.date() for x in ts}),
                   "usual_time": part_of_day(int(median(x.hour for x in ts)))} for (k, t), ts in top],
        "commands": [{"intent": name, "count": n} for name, n in commands.most_common(8)],
        "events": len(parsed),
    }


COMMAND_LABELS = {
    "open_app": "apps kholna", "system_info": "system ki maloomat", "web_search": "web search", "open_website":
    "websites", "search_files": "files dhoondna", "read_file": "files parhna", "open_project": "projects kholna",
    "run_tests": "tests chalana", "change_setting": "settings", "send_message": "messages", "research": "research",
    "web_answer": "taza jawab", "remember_fact": "baatein yaad karwana", "run_workflow": "workflows",
}


def describe(data: dict[str, Any]) -> str:
    """Roman Urdu summary for "meri aadatein batao"."""
    if not data["items"] and not data["commands"]:
        return "Abhi aap ki koi aadat nazar nahi aayi — NOVA ke sath kuch din kaam ke baad yahan nazar aayengi."
    lines = []
    if data["items"]:
        lines.append("Aap aksar ye kholte hain (pichle 30 din):")
        lines += [f"- {i['target']}{' project' if i['kind'] == 'project' else ''}: {i['count']} dafa, {i['days']} din, "
                  f"zyada tar {i['usual_time']}" for i in data["items"][:6]]
    if data["commands"]:
        names = [COMMAND_LABELS.get(c["intent"], c["intent"].replace("_", " ")) for c in data["commands"][:5]]
        lines.append("Sab se zyada kaam: " + ", ".join(names) + ".")
    return "\n".join(lines)
