"""Turn tool output (Python, pytest, TypeScript, ESLint, PHP, Node, Jest/Vitest) into structured errors."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CodeError:
    message: str
    file: str | None = None  # absolute path when it could be resolved
    line: int | None = None
    tool: str = ""

    def where(self, root: Path | None = None) -> str:
        if not self.file:
            return ""
        shown = self.file
        if root is not None:
            try:
                shown = str(Path(self.file).relative_to(root))
            except ValueError:
                pass
        return f"{shown}:{self.line}" if self.line else shown


PY_FRAME = re.compile(r'^\s*(?:\*\*\*\s+)?File "(?P<file>[^"]+)", line (?P<line>\d+)')
PY_EXC = re.compile(r"^(?P<exc>[A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning)):?\s?(?P<msg>.*)$")
PYTEST_FAILED = re.compile(r"^(?:FAILED|ERROR) (?P<file>[^\s:]+\.py)(?:::(?P<test>\S+))?(?: - (?P<msg>.+))?$")
PYTEST_LOC = re.compile(r"^(?P<file>[^\s:]+\.py):(?P<line>\d+): (?P<msg>.+)$")
TS_PAREN = re.compile(r"^(?P<file>[^\s(]+\.(?:ts|tsx|js|jsx|vue|mts|cts))\((?P<line>\d+),\d+\): error (?P<code>TS\d+): (?P<msg>.+)$")
TS_COLON = re.compile(r"^(?P<file>[^\s:]+\.(?:ts|tsx|js|jsx|vue|mts|cts)):(?P<line>\d+):\d+ - error (?P<code>TS\d+): (?P<msg>.+)$")
# ESLint prints each file's path on its own line (it may contain spaces), then its problems.
ESLINT_FILE = re.compile(r"^(?P<file>(?:[A-Za-z]:[\\/]|[\\/]|\.{1,2}[\\/])?[^:*?\"<>|\s][^:*?\"<>|]*\.(?:js|jsx|ts|tsx|vue|mjs|cjs))$")
ESLINT_ROW = re.compile(r"^\s+(?P<line>\d+):\d+\s+error\s+(?P<msg>.+?)(?:\s{2,}\S+)?$")
PHP_ERR = re.compile(r"(?:PHP\s+)?(?P<kind>Parse error|Fatal error|Warning|Deprecated):\s+(?P<msg>.+?) in (?P<file>.+?) on line (?P<line>\d+)")
NODE_LOC = re.compile(r"^(?P<file>(?:[A-Za-z]:)?[\\/][^:]+?\.(?:m?js|cjs)):(?P<line>\d+)$")
NODE_EXC = re.compile(r"^(?P<exc>\w*Error): (?P<msg>.+)$")
VITEST_LOC = re.compile(r"(?:❯|at )\s*(?:\S+ \()?(?P<file>[^\s()]+\.(?:ts|tsx|js|jsx|mjs)):(?P<line>\d+):\d+\)?")
JEST_FAIL = re.compile(r"^\s*(?:FAIL|×|✕)\s+(?P<file>\S+\.(?:ts|tsx|js|jsx|mjs))(?:\s+>\s+(?P<test>.+))?")


def _resolve(file: str, root: Path) -> str:
    path = Path(file)
    if not path.is_absolute():
        path = root / path
    return os.path.normpath(path)


def parse_errors(output: str, root: Path, limit: int = 20) -> list[CodeError]:
    errors: list[CodeError] = []
    lines = output.splitlines()
    last_frame: tuple[str, int] | None = None
    last_project_frame: tuple[str, int] | None = None
    node_loc: tuple[str, int] | None = None
    eslint_file: str | None = None

    def add(err: CodeError) -> None:
        key = (err.file, err.line, err.message)
        if all((e.file, e.line, e.message) != key for e in errors):
            errors.append(err)

    for raw in lines:
        line = raw.rstrip()
        if m := PHP_ERR.search(line):
            add(CodeError(f"{m['kind']}: {m['msg']}", _resolve(m["file"], root), int(m["line"]), "php"))
            continue
        if m := PY_FRAME.match(line):
            last_frame = (m["file"], int(m["line"]))
            if "site-packages" not in m["file"] and "<frozen" not in m["file"]:
                last_project_frame = last_frame
            continue
        if m := PYTEST_FAILED.match(line):
            add(CodeError(m["msg"] or f"Test fail hua: {m['test'] or m['file']}", _resolve(m["file"], root), None, "pytest"))
            continue
        if m := PYTEST_LOC.match(line):
            add(CodeError(m["msg"], _resolve(m["file"], root), int(m["line"]), "pytest"))
            continue
        if m := TS_PAREN.match(line) or TS_COLON.match(line):
            add(CodeError(f"{m['code']}: {m['msg']}", _resolve(m["file"], root), int(m["line"]), "typescript"))
            continue
        if m := ESLINT_FILE.match(line.strip()):
            eslint_file = m["file"]
            continue
        if eslint_file and (m := ESLINT_ROW.match(line)):
            add(CodeError(m["msg"], _resolve(eslint_file, root), int(m["line"]), "eslint"))
            continue
        if m := NODE_LOC.match(line.strip()):
            node_loc = (m["file"], int(m["line"]))
            continue
        if m := JEST_FAIL.match(line):
            add(CodeError(f"Test fail hua: {m['test'] or m['file']}", _resolve(m["file"], root), None, "tests"))
            continue
        if (m := VITEST_LOC.search(line)) and "node_modules" not in m["file"]:
            for e in errors:
                if e.tool == "tests" and e.line is None and e.file and Path(e.file).name == Path(m["file"]).name:
                    e.line = int(m["line"])
            continue
        if m := PY_EXC.match(line.strip()):
            frame = last_project_frame or last_frame
            if frame or m["exc"] in ("SyntaxError", "IndentationError", "TabError"):
                msg = f"{m['exc']}: {m['msg']}".rstrip(": ")
                add(CodeError(msg, _resolve(frame[0], root) if frame else None, frame[1] if frame else None, "python"))
                last_frame = last_project_frame = None
                continue
        if node_loc and (m := NODE_EXC.match(line.strip())):
            add(CodeError(f"{m['exc']}: {m['msg']}", _resolve(node_loc[0], root), node_loc[1], "node"))
            node_loc = None
        if len(errors) >= limit:
            break
    return errors


def summarize_tests(output: str) -> str | None:
    """"3 passed, 1 failed" style one-liner from pytest/Jest/Vitest/PHPUnit output."""
    text = output[-6000:]
    if m := re.search(r"=+ (?P<s>[^=]*\b(?:passed|failed|error)[^=]*) in [\d.]+s", text):  # pytest
        return m["s"].strip()
    if m := re.search(r"Tests:\s+(?P<s>[^\n]*\btotal)", text):  # Jest
        return m["s"].strip()
    if m := re.search(r"Tests\s+(?P<s>[^\n]*\((\d+)\))", text):  # Vitest
        return m["s"].strip()
    if m := re.search(r"OK \((?P<n>\d+) tests?", text):  # PHPUnit
        return f"{m['n']} passed"
    if m := re.search(r"Tests: (?P<t>\d+), Assertions: \d+(?:, (?:Failures|Errors): (?P<f>\d+))?", text):
        return f"{m['t']} tests, {m['f'] or 0} failed"
    return None
