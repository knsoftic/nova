"""LOGS.md and README.md as the admin's record: read each phase's status, write approvals, bug lines and the daily
system-activity summary - changing only those lines, never the rest of the developer's text."""

from __future__ import annotations

import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

TASK = re.compile(r"^### Task: (?P<title>.+)$", re.MULTILINE)
PHASE_ID = re.compile(r"\bPhase\s+(?P<id>\d+[A-Z]?)\b")
README_TEST = re.compile(r"^## Admin manual test \(Phase (?P<id>\d+[A-Z]?)(?:, approved)?\)\s*$", re.MULTILINE)
BUGS_HEADING = "Admin bugs:"
SYSTEM_HEADING = "## System activity (rozana khulasa)"
_lock = threading.Lock()


@dataclass
class LogTask:
    phase: str
    title: str
    status: str
    admin_test: str
    admin_approval: str
    has_test: bool
    bugs: list[str] = field(default_factory=list)
    start: int = 0
    end: int = 0

    @property
    def approved(self) -> bool:
        return self.admin_approval.lower().startswith("approved")


def _value(block: str, label: str) -> str:
    m = re.search(rf"^{re.escape(label)}\n(?P<v>[^\n]*)", block, re.MULTILINE)
    return m["v"].strip() if m else ""


def _blocks(text: str) -> list[tuple[str, int, int]]:
    """(title, start, end) of every task block; a block ends at the next task, "---" line or "## " heading."""
    out = []
    starts = list(TASK.finditer(text))
    for i, m in enumerate(starts):
        limit = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        stop = re.search(r"^(?:---\s*$|## )", text[m.end():limit], re.MULTILINE)
        out.append((m["title"].strip(), m.start(), m.end() + stop.start() if stop else limit))
    return out


def parse_tasks(text: str) -> list[LogTask]:
    tasks = []
    for title, start, end in _blocks(text):
        block = text[start:end]
        m = PHASE_ID.search(title)
        bugs_at = block.find(f"\n{BUGS_HEADING}\n")
        bugs = []
        if bugs_at >= 0:
            for line in block[bugs_at + len(BUGS_HEADING) + 2:].splitlines():
                if not line.startswith("- "):
                    break
                bugs.append(line[2:])
        status = re.search(r"^Status: (?P<v>.+)$", block, re.MULTILINE)
        tasks.append(LogTask(
            phase=m["id"] if m else title, title=title, status=status["v"].strip() if status else "",
            admin_test=_value(block, "Admin Test:"), admin_approval=_value(block, "Admin Approval:"),
            has_test=bool(re.search(r"^Test:\s*$", block, re.MULTILINE)), bugs=bugs, start=start, end=end))
    return tasks


def find(text: str, phase: str) -> LogTask | None:
    return next((t for t in parse_tasks(text) if t.phase.lower() == phase.lower()), None)


def _set_value(block: str, label: str, value: str) -> str:
    pattern = re.compile(rf"^({re.escape(label)}\n)[^\n]*", re.MULTILINE)
    if pattern.search(block):
        return pattern.sub(lambda m: m.group(1) + value, block, count=1)
    return block.rstrip("\n") + f"\n\n{label}\n{value}\n"


def set_admin(text: str, phase: str, admin_test: str | None = None, admin_approval: str | None = None) -> str:
    task = find(text, phase)
    if task is None:
        raise KeyError(phase)
    block = text[task.start:task.end]
    if admin_test is not None:
        block = _set_value(block, "Admin Test:", admin_test)
    if admin_approval is not None:
        block = _set_value(block, "Admin Approval:", admin_approval)
    return text[:task.start] + block + text[task.end:]


def set_bug(text: str, phase: str, bug_id: int, line: str) -> str:
    """Add or replace "- #<id> ..." under "Admin bugs:" in the phase's block (the section is created before
    "Admin Test:" when missing)."""
    task = find(text, phase)
    if task is None:
        raise KeyError(phase)
    block = text[task.start:task.end]
    entry = f"- #{bug_id} {line}"
    existing = re.compile(rf"^- #{bug_id} .*$", re.MULTILINE)
    if existing.search(block):
        block = existing.sub(lambda m: entry, block, count=1)
    elif f"\n{BUGS_HEADING}\n" in block:
        at = block.index(f"\n{BUGS_HEADING}\n") + len(BUGS_HEADING) + 2
        lines_end = at
        for line in block[at:].splitlines(keepends=True):
            if not line.startswith("- "):
                break
            lines_end += len(line)
        block = block[:lines_end] + entry + "\n" + block[lines_end:]
    else:
        at = block.find("\nAdmin Test:\n")
        section = f"\n{BUGS_HEADING}\n{entry}\n"
        block = block[:at] + section + block[at:] if at >= 0 else block.rstrip("\n") + f"\n{section}"
    return text[:task.start] + block + text[task.end:]


def upsert_summary(text: str, date: str, line: str) -> str:
    """One line per day under the system-activity section at the end of LOGS.md (added once, never rewritten)."""
    entry = f"- {date}: {line}"
    if SYSTEM_HEADING not in text:
        return text.rstrip("\n") + f"\n\n---\n\n{SYSTEM_HEADING}\n\n{entry}\n"
    section = text[text.index(SYSTEM_HEADING):]
    if re.search(rf"^- {re.escape(date)}:", section, re.MULTILINE):
        return text
    return text.rstrip("\n") + f"\n{entry}\n"


def summary_dates(text: str) -> set[str]:
    if SYSTEM_HEADING not in text:
        return set()
    return set(re.findall(r"^- (\d{4}-\d{2}-\d{2}):", text[text.index(SYSTEM_HEADING):], re.MULTILINE))


def readme_steps(readme: str) -> dict[str, list[str]]:
    """Admin manual test steps per phase from README.md."""
    out: dict[str, list[str]] = {}
    heads = list(README_TEST.finditer(readme))
    for m in heads:
        rest = readme[m.end():]
        stop = re.search(r"^## ", rest, re.MULTILINE)
        body = rest[: stop.start()] if stop else rest
        steps: list[str] = []
        for line in body.strip().splitlines():
            if re.match(r"^\d+\.\s", line):
                steps.append(re.sub(r"^\d+\.\s+", "", line).strip())
            elif steps and line.startswith("   "):
                steps[-1] += " " + line.strip()
            elif line.strip() and not steps:
                steps.append(line.strip())
        out[m["id"]] = steps
    return out


class DocFile:
    """A text file NOVA may update in place (atomic write, one writer at a time)."""

    def __init__(self, path: Path | None) -> None:
        self.path = path

    @property
    def available(self) -> bool:
        return self.path is not None and self.path.is_file()

    def read(self) -> str:
        if not self.available:
            return ""
        return self.path.read_text(encoding="utf-8")  # type: ignore[union-attr]

    def update(self, change) -> str:
        """Apply `change(text) -> text` and write it back atomically. Returns the new text."""
        if not self.available:
            raise FileNotFoundError(str(self.path))
        with _lock:
            text = self.path.read_text(encoding="utf-8")  # type: ignore[union-attr]
            new = change(text)
            if new != text:
                fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".logs-", suffix=".tmp")  # type: ignore
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                    f.write(new)
                os.replace(tmp, self.path)  # type: ignore[arg-type]
            return new
