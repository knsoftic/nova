"""All automated checks in one go (Phase 11): code check, backend tests, frontend tests, typecheck, build.

    .venv\\Scripts\\python.exe scripts\\check_all.py [--quick]

--quick skips the frontend build. Prints a Roman Urdu summary; the exit code is 0 only when everything passed.
Nothing here touches the user's files, settings or LOGS.md (the backend tests use their own temporary data).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
DESKTOP = BACKEND.parent / "desktop"
PYTHON = sys.executable
NPM = shutil.which("npm") or "npm"


def run(name: str, cmd: list[str], cwd: Path, summary: re.Pattern[str] | None = None) -> tuple[str, bool, str, float]:
    started = time.perf_counter()
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          shell=cmd[0] == NPM and sys.platform == "win32")
    took = time.perf_counter() - started
    out = (proc.stdout or "") + (proc.stderr or "")
    detail = ""
    if summary and (m := summary.search(out)):
        detail = m.group(0).strip()
    elif proc.returncode != 0:
        detail = out.strip().splitlines()[-1][:160] if out.strip() else f"exit {proc.returncode}"
    return name, proc.returncode == 0, detail, took


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="frontend build chhor dein")
    args = parser.parse_args()
    steps = [
        ("Code check (pyflakes)", [PYTHON, "-m", "pyflakes", "nova", "tests", "scripts"], BACKEND, None),
        ("Backend tests (pytest)", [PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider"], BACKEND,
         re.compile(r"\d+ (?:passed|failed)[^\n]*")),
        ("Frontend tests (vitest)", [NPM, "test"], DESKTOP, re.compile(r"Tests\s+[^\n]+")),
        ("TypeScript typecheck", [NPM, "run", "typecheck"], DESKTOP, None),
    ]
    if not args.quick:
        steps.append(("Frontend build", [NPM, "run", "build"], DESKTOP, re.compile(r"built in [\d.]+m?s")))
    results = []
    for name, cmd, cwd, summary in steps:
        print(f"... {name}", flush=True)
        results.append(run(name, cmd, cwd, summary))
    print()
    for name, ok, detail, took in results:
        print(f"{'THEEK ' if ok else 'NAKAAM'}  {name:<26} {took:6.1f}s  {re.sub(r'\x1b\[[0-9;]*m', '', detail)}")
    failed = [r for r in results if not r[1]]
    print("\nSab automated tests theek hain." if not failed else f"\n{len(failed)} hisse nakaam — upar dekhein.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
