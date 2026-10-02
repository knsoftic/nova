"""Development commands for the Coding Agent - chosen from a fixed list, never an arbitrary command line.

Allowed: the project's own npm scripts (names read from package.json), dependency installs, the project's
tests (npm test, pytest with the project's .venv, PHPUnit), read-only git commands, and built-in syntax
checks (python compileall, php -l, node --check). Commands run without a shell, inside the project folder,
with a timeout; if one runs too long its whole process tree is stopped.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .projects import NPM_PLACEHOLDER_TEST, ProjectInfo

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010
SCRIPT_NAME = re.compile(r"^[\w:.\-]{1,60}$")
LONG_RUNNING_SCRIPTS = {"dev", "start", "serve", "watch", "develop", "preview"}
LONG_RUNNING_COMMAND = re.compile(r"\b(?:vite(?!\s+build)|next\s+dev|nodemon|webpack\s+serve|react-scripts\s+start|"
                                  r"ng\s+serve|electron\s+\.|--watch|concurrently)\b")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
MAX_LINT_FILES = 300
OUTPUT_LINES = 4000


@dataclass
class Tools:
    npm: str | None = None
    node: str | None = None
    python: str | None = None
    php: str | None = None
    git: str | None = None
    code: str | None = None  # VS Code (Code.exe)
    composer: str | None = None


def find_tools() -> Tools:
    def which(*names: str) -> str | None:
        for name in names:
            path = shutil.which(name)
            if path and "windowsapps" not in path.lower():  # skip the Store "python" stub
                return path
        return None

    php = which("php") or next((p for p in (r"C:\xampp\php\php.exe",) if Path(p).is_file()), None)
    code = None
    if launcher := which("code.cmd", "code"):
        exe = Path(launcher).resolve().parent.parent / "Code.exe"
        code = str(exe) if exe.is_file() else None
    if code is None:
        for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles", "")):
            exe = Path(base) / ("Programs" if "Local" in base else "") / "Microsoft VS Code" / "Code.exe"
            if base and exe.is_file():
                code = str(exe)
                break
    return Tools(npm=which("npm.cmd", "npm"), node=which("node"), python=which("python", "py"), php=php,
                 git=which("git"), code=code, composer=which("composer.bat", "composer"))


@dataclass
class CommandSpec:
    argv: list[str]
    cwd: Path
    label: str  # what the user sees: "npm test", "python -m pytest -q"
    kind: str  # test | script | install | server | git | check
    timeout: float = 300.0
    runs_project_code: bool = True  # the project's own code/scripts execute
    network: bool = False  # downloads packages from the internet
    long_running: bool = False  # a dev server: runs in its own terminal window
    files: list[Path] | None = None  # per-file checks (php -l, node --check): argv + each file


@dataclass
class RunResult:
    exit_code: int | None
    output: str
    seconds: float
    timed_out: bool = False
    failed_files: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ planning


def plan_tests(info: ProjectInfo, tools: Tools) -> CommandSpec | str:
    test_script = info.scripts.get("test")
    if "node" in info.kinds and test_script and not NPM_PLACEHOLDER_TEST.search(test_script):
        if not tools.npm:
            return "npm is PC par nahi mila (Node.js install karein)."
        return CommandSpec([tools.npm, "test"], info.path, "npm test", "test", timeout=600)
    if "python" in info.kinds and info.has_tests:
        python = str(info.venv_python) if info.venv_python else tools.python
        if not python:
            return "Python is PC par nahi mila."
        label = "python -m pytest -q" + (" (.venv)" if info.venv_python else "")
        return CommandSpec([python, "-m", "pytest", "-q"], info.path, label, "test", timeout=600)
    phpunit = info.path / "vendor" / "bin" / "phpunit"
    if "php" in info.kinds and phpunit.exists() and tools.php:
        return CommandSpec([tools.php, str(phpunit)], info.path, "phpunit", "test", timeout=600)
    return f"\"{info.name}\" mein tests nahi mile."


def plan_checks(info: ProjectInfo, tools: Tools) -> list[CommandSpec] | str:
    specs: list[CommandSpec] = []
    if "node" in info.kinds:
        for script in ("typecheck", "type-check", "lint"):
            if script in info.scripts and tools.npm:
                specs.append(CommandSpec([tools.npm, "run", script], info.path, f"npm run {script}", "check", 300))
        tsc = info.path / "node_modules" / ".bin" / "tsc.cmd"
        if not specs and (info.path / "tsconfig.json").is_file() and tsc.is_file():
            specs.append(CommandSpec([str(tsc), "--noEmit"], info.path, "tsc --noEmit", "check", 300))
        if not specs and tools.node and not {"React", "Vue", "Svelte", "Angular", "Next.js"} & set(info.frameworks):
            files = _files(info.path, (".js", ".mjs", ".cjs"))
            if files:
                specs.append(CommandSpec([tools.node, "--check"], info.path, f"node --check ({len(files)} files)",
                                         "check", 60, runs_project_code=False, files=files))
    if "python" in info.kinds:
        python = str(info.venv_python) if info.venv_python else tools.python
        if python:
            specs.append(CommandSpec([python, "-m", "compileall", "-q", "-x",
                                      r"[\\/](?:\.venv|venv|env|node_modules|\.git|build|dist)[\\/]", "."],
                                     info.path, "python -m compileall", "check", 120, runs_project_code=False))
    if "php" in info.kinds and tools.php:
        files = _files(info.path, (".php",))
        if files:
            specs.append(CommandSpec([tools.php, "-l"], info.path, f"php -l ({len(files)} files)", "check", 60,
                                     runs_project_code=False, files=files))
    return specs or f"\"{info.name}\" ke liye errors check karne ka tareeqa nahi mila."


def plan_command(info: ProjectInfo, request: str, tools: Tools, xampp_url: str | None = None) -> CommandSpec | str:
    r = " ".join(request.lower().split())
    if re.search(r"\btests?\b", r):
        return plan_tests(info, tools)
    if r.startswith("git"):
        words = r.split()
        sub = words[1] if len(words) > 1 else "status"
        args = {"status": ["status", "--short", "--branch"], "diff": ["diff", "--stat"],
                "log": ["log", "--oneline", "-15"]}.get(sub)
        if args is None:
            return "Git ki sirf parhne wali commands chalti hain: git status, git diff, git log."
        if not tools.git:
            return "Git is PC par nahi mila."
        return CommandSpec([tools.git, *args], info.path, "git " + " ".join(args), "git", 30, runs_project_code=False)
    if re.search(r"\b(?:install|dependencies|packages)\b", r):
        if "node" in info.kinds:
            if not tools.npm:
                return "npm is PC par nahi mila (Node.js install karein)."
            return CommandSpec([tools.npm, "install"], info.path, "npm install", "install", 900, network=True)
        if "python" in info.kinds and (info.path / "requirements.txt").is_file():
            if not info.venv_python:
                return ("Is project ka apna .venv nahi — NOVA system Python mein packages install nahi karta. Pehle "
                        "project mein virtual environment banayein.")
            return CommandSpec([str(info.venv_python), "-m", "pip", "install", "-r", "requirements.txt"], info.path,
                               "pip install -r requirements.txt (.venv)", "install", 900, network=True)
        if (info.path / "composer.json").is_file() and tools.composer:
            return CommandSpec([tools.composer, "install", "--no-interaction"], info.path, "composer install",
                               "install", 900, network=True)
        return "Is project mein install karne ke liye kuch nahi mila."
    name = re.sub(r"^(?:npm\s+)?(?:run\s+)?", "", r).strip()
    if name in ("server", "dev server", "development server", "chala", "app", "project"):
        if "node" not in info.kinds:
            if "php" in info.kinds and xampp_url:
                return f"Ye PHP project XAMPP (Apache) se chalta hai: {xampp_url} — Apache XAMPP Control Panel se start karein."
            return "Is project mein server chalane ka script nahi mila."
        name = next((s for s in ("dev", "start", "serve") if s in info.scripts), name)
    if name in info.scripts and SCRIPT_NAME.match(name):
        if not tools.npm:
            return "npm is PC par nahi mila (Node.js install karein)."
        value = info.scripts[name]
        long_running = (name in LONG_RUNNING_SCRIPTS or bool(LONG_RUNNING_COMMAND.search(value))) and "build" not in name
        return CommandSpec([tools.npm, "run", name], info.path, f"npm run {name}", "server" if long_running else "script",
                           600, long_running=long_running)
    if info.scripts:
        return f"\"{request}\" is project ka script nahi. Mojood scripts: {', '.join(list(info.scripts)[:10])}."
    return f"\"{request}\" NOVA nahi chala sakta — sirf project ke npm scripts, tests, install aur git status/diff/log."


def _files(root: Path, exts: tuple[str, ...]) -> list[Path]:
    from ..files.finder import SKIP_DIRS

    found: list[Path] = []
    for folder, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not d.startswith(".")]
        found += [Path(folder) / n for n in names if n.lower().endswith(exts)]
        if len(found) >= MAX_LINT_FILES:
            return found[:MAX_LINT_FILES]
    return found


# ------------------------------------------------------------------ running


def _env() -> dict[str, str]:
    env = os.environ.copy()
    # Non-interactive, no colours, UTF-8 output; test runners stop watching when CI is set.
    env.update(CI="true", FORCE_COLOR="0", NO_COLOR="1", PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               npm_config_fund="false", npm_config_audit="false", npm_config_update_notifier="false")
    return env


def _kill_tree(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=CREATE_NO_WINDOW)


def run(spec: CommandSpec, on_progress: Callable[[str], None] | None = None) -> RunResult:
    started = time.monotonic()
    if spec.files is not None:
        return _run_per_file(spec, started)
    proc = subprocess.Popen(spec.argv, cwd=spec.cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, env=_env(), creationflags=CREATE_NO_WINDOW)
    lines: deque[str] = deque(maxlen=OUTPUT_LINES)

    def reader() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            lines.append(ANSI.sub("", raw.decode("utf-8", errors="replace").rstrip("\r\n")))

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    timed_out = False
    last_report = started
    while proc.poll() is None:
        time.sleep(0.25)
        now = time.monotonic()
        if now - started > spec.timeout:
            timed_out = True
            _kill_tree(proc.pid)
            break
        if on_progress and now - last_report > 4 and lines:
            last_report = now
            on_progress(lines[-1][:160])
    proc.wait(timeout=10)
    thread.join(timeout=5)
    return RunResult(None if timed_out else proc.returncode, "\n".join(lines), time.monotonic() - started, timed_out)


def _run_per_file(spec: CommandSpec, started: float) -> RunResult:
    out: list[str] = []
    failed: list[str] = []
    for path in spec.files or []:
        try:
            p = subprocess.run([*spec.argv, str(path)], cwd=spec.cwd, capture_output=True, timeout=30,
                               stdin=subprocess.DEVNULL, env=_env(), creationflags=CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:
            failed.append(str(path))
            out.append(f"{path}: timeout")
            continue
        if p.returncode != 0:
            failed.append(str(path))
            text = (p.stdout + p.stderr).decode("utf-8", errors="replace")
            out.append(ANSI.sub("", text.strip()))
        if time.monotonic() - started > spec.timeout:
            out.append("(waqt khatam — baqi files check nahi hui)")
            break
    return RunResult(1 if failed else 0, "\n".join(out), time.monotonic() - started, False, failed)


def start_server(spec: CommandSpec, wait_s: float = 5.0) -> tuple[bool, int | None]:
    """Dev servers run in their own terminal window (the user sees the output and can close it)."""
    proc = subprocess.Popen(spec.argv, cwd=spec.cwd, env=_env(), creationflags=CREATE_NEW_CONSOLE)
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False, proc.pid
        time.sleep(0.25)
    return True, proc.pid
