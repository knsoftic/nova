"""Find and describe code projects inside the project folders (default C:\\xampp\\htdocs)."""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..files.finder import SKIP_DIRS

MARKERS = ("package.json", "composer.json", "requirements.txt", "pyproject.toml", "setup.py", "manage.py", "artisan",
           "index.php", "index.html", ".git", "go.mod", "Cargo.toml", "pom.xml")
LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "React (JSX)",
    ".ts": "TypeScript", ".tsx": "React (TSX)", ".php": "PHP", ".html": "HTML", ".htm": "HTML", ".css": "CSS",
    ".scss": "SCSS", ".vue": "Vue", ".java": "Java", ".cs": "C#", ".go": "Go", ".rs": "Rust", ".rb": "Ruby",
    ".sql": "SQL", ".dart": "Dart", ".kt": "Kotlin", ".c": "C", ".cpp": "C++",
}
# npm's placeholder "test" script only prints an error.
NPM_PLACEHOLDER_TEST = re.compile(r"no test specified", re.IGNORECASE)
CREATE_NO_WINDOW = 0x08000000


@dataclass
class Project:
    name: str
    path: Path


@dataclass
class ProjectInfo:
    name: str
    path: Path
    kinds: list[str] = field(default_factory=list)  # node, php, python, static
    frameworks: list[str] = field(default_factory=list)
    scripts: dict[str, str] = field(default_factory=dict)
    languages: dict[str, int] = field(default_factory=dict)
    files: int = 0
    size: int = 0
    git_branch: str | None = None
    git_changes: int | None = None
    readme: str | None = None
    has_tests: bool = False
    venv_python: Path | None = None
    has_node_modules: bool = False
    has_vendor: bool = False
    partial: bool = False


def _norm(name: str) -> str:
    return re.sub(r"[\s_\-.]+", " ", name.lower()).strip()


def list_projects(roots: list[Path]) -> list[Project]:
    projects: list[Project] = []
    for root in roots:
        # A project folder added directly in Settings is itself a project. index.php/index.html do not count:
        # XAMPP's own htdocs has an index.php next to the user's projects.
        if any((root / m).exists() for m in MARKERS if m not in ("index.php", "index.html")):
            projects.append(Project(root.name, root))
            continue
        try:
            children = sorted(os.scandir(root), key=lambda e: e.name.lower())
        except OSError:
            continue
        for entry in children:
            if entry.is_dir() and not entry.name.startswith((".", "$")):
                projects.append(Project(entry.name, Path(entry.path)))
    return projects


def find_project(name: str, projects: list[Project]) -> Project | list[Project] | None:
    """Exact name, then prefix, then contains, then close spelling. Several equally good -> the list."""
    wanted = _norm(re.sub(r"\s+(?:project|projects|folder)$", "", name.strip(), flags=re.IGNORECASE))
    if not wanted:
        return None
    named = [(p, _norm(p.name)) for p in projects]
    for tier in (
        [p for p, n in named if n == wanted],
        [p for p, n in named if n.replace(" ", "") == wanted.replace(" ", "")],
        [p for p, n in named if n.startswith(wanted)],
        [p for p, n in named if wanted in n],
    ):
        if len(tier) == 1:
            return tier[0]
        if tier:
            return tier
    close = difflib.get_close_matches(wanted, [n for _p, n in named], n=3, cutoff=0.75)
    matches = [p for p, n in named if n in close]
    return matches[0] if len(matches) == 1 else (matches or None)


def project_python(path: Path) -> Path | None:
    for venv in (".venv", "venv", "env"):
        candidate = path / venv / "Scripts" / "python.exe"
        if candidate.is_file():
            return candidate
    return None


def inspect(path: Path, git: str | None = None, budget_files: int = 30_000) -> ProjectInfo:
    info = ProjectInfo(path.name, path)
    pkg = path / "package.json"
    if pkg.is_file():
        info.kinds.append("node")
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = {}
        scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
        info.scripts = {str(k): str(v) for k, v in scripts.items()}
        deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
        for dep, label in (("next", "Next.js"), ("react", "React"), ("vue", "Vue"), ("svelte", "Svelte"),
                           ("@angular/core", "Angular"), ("electron", "Electron"), ("express", "Express"),
                           ("vite", "Vite"), ("tailwindcss", "Tailwind"), ("typescript", "TypeScript")):
            if dep in deps:
                info.frameworks.append(label)
        if (test := info.scripts.get("test")) and not NPM_PLACEHOLDER_TEST.search(test):
            info.has_tests = True
    if (path / "composer.json").is_file() or any(path.glob("*.php")):
        info.kinds.append("php")
        if (path / "artisan").is_file():
            info.frameworks.append("Laravel")
        if (path / "vendor" / "bin" / "phpunit").exists():
            info.has_tests = True
    if any((path / m).is_file() for m in ("requirements.txt", "pyproject.toml", "setup.py", "manage.py")) or any(
            path.glob("*.py")):
        info.kinds.append("python")
        if (path / "manage.py").is_file():
            info.frameworks.append("Django")
        if (path / "tests").is_dir() or (path / "pytest.ini").is_file() or any(path.glob("test_*.py")):
            info.has_tests = True
        info.venv_python = project_python(path)
    if not info.kinds and any(path.glob("*.htm*")):
        info.kinds.append("static")
    info.has_node_modules = (path / "node_modules").is_dir()
    info.has_vendor = (path / "vendor").is_dir()
    for readme in ("README.md", "readme.md", "README.txt", "README"):
        if (path / readme).is_file():
            try:
                lines = [ln.strip("# ").strip() for ln in (path / readme).read_text(encoding="utf-8", errors="replace")
                         .splitlines() if ln.strip()]
                info.readme = lines[0][:160] if lines else None
            except OSError:
                pass
            break
    seen = 0
    for root, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS and not d.startswith(".")]
        for name in names:
            seen += 1
            info.files += 1
            lang = LANGUAGES.get(Path(name).suffix.lower())
            if lang:
                info.languages[lang] = info.languages.get(lang, 0) + 1
            try:
                info.size += (Path(root) / name).stat().st_size
            except OSError:
                pass
        if seen > budget_files:
            info.partial = True
            break
    if git and (path / ".git").exists():
        try:
            branch = subprocess.run([git, "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True,
                                    text=True, timeout=5, creationflags=CREATE_NO_WINDOW)
            status = subprocess.run([git, "-C", str(path), "status", "--porcelain"], capture_output=True, text=True,
                                    timeout=10, creationflags=CREATE_NO_WINDOW)
            if branch.returncode == 0:
                info.git_branch = branch.stdout.strip()
            if status.returncode == 0:
                info.git_changes = len([ln for ln in status.stdout.splitlines() if ln.strip()])
        except (OSError, subprocess.TimeoutExpired):
            pass
    return info


def describe(info: ProjectInfo, size_text) -> str:
    kinds = {"node": "Node.js", "php": "PHP", "python": "Python", "static": "HTML website"}
    kind = ", ".join(kinds[k] for k in info.kinds) or "pehchana nahi gaya"
    lines = [f"Project \"{info.name}\" ({info.path}):", f"- Qism: {kind}" + (
        f" ({', '.join(info.frameworks)})" if info.frameworks else "")]
    if info.languages:
        top = sorted(info.languages.items(), key=lambda kv: -kv[1])[:5]
        lines.append("- Files: " + f"{info.files}{'+' if info.partial else ''} ({size_text(info.size)}) — "
                     + ", ".join(f"{lang} {n}" for lang, n in top))
    else:
        lines.append(f"- Files: {info.files} ({size_text(info.size)})")
    if info.scripts:
        lines.append("- npm scripts: " + ", ".join(list(info.scripts)[:8]))
    if info.git_branch:
        lines.append(f"- Git: branch {info.git_branch}" + (
            f", {info.git_changes} badli hui files" if info.git_changes else ", sab kuch commit hai"))
    lines.append("- Tests: " + ("hain" if info.has_tests else "nahi mile"))
    if "node" in info.kinds and not info.has_node_modules:
        lines.append("- node_modules nahi — pehle dependencies install karni hongi.")
    if "python" in info.kinds:
        lines.append("- Python environment: " + (".venv mila" if info.venv_python else "project ka apna .venv nahi"))
    if info.readme:
        lines.append(f"- README: {info.readme}")
    return "\n".join(lines)
