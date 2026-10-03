"""Assemble what the installer ships next to the app (Phase 12): a private Python, NOVA's backend, the voice models.

    .venv\\Scripts\\python.exe scripts\\build_runtime.py [--out ..\\desktop\\build\\runtime] [--no-models]

- python/  a copy of the interpreter this venv was made from (CPython on Windows runs from any folder) plus the
           packages already installed in this venv - no internet needed - minus tests and developer tools.
- backend/ the `nova` package.
- models/  the Whisper and Piper voice models from data/models (the offline installer).
Verified at the end by running `python -m nova --check` with the new runtime.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PROJECT = BACKEND.parent
DEFAULT_OUT = PROJECT / "desktop" / "build" / "runtime"

# Not needed to run NOVA: CPython's own tests, IDLE/Tk, docs, headers, and the developer tools from requirements-dev.
SKIP_TOP = {"Doc", "Tools", "include", "libs", "tcl", "Scripts", "Lib"}
SKIP_LIB = {"test", "idlelib", "tkinter", "turtledemo", "ensurepip", "venv", "site-packages", "__pycache__",
            "unittest" + os.sep + "test"}
DEV_PACKAGES = ("pytest", "_pytest", "pluggy", "iniconfig", "pyflakes", "pip", "py.py")
NEVER = {"__pycache__"}


def skip_name(name: str) -> bool:
    return name in NEVER or name.endswith((".pyc", ".pdb"))


def is_dev_package(name: str) -> bool:
    low = name.lower()
    return any(low == p or low.startswith(p.replace(".py", "") + "-") for p in DEV_PACKAGES)


def copy_tree(src: Path, dst: Path, skip=lambda rel, name: False) -> int:
    """Copy `src` into `dst` (following links), leaving out what `skip(relative_dir, name)` says. Returns bytes."""
    total = 0
    for root, dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        dirs[:] = [d for d in dirs if not skip_name(d) and not skip(rel, d)]
        target = dst / rel if rel != "." else dst
        target.mkdir(parents=True, exist_ok=True)
        for f in files:
            if skip_name(f) or skip(rel, f):
                continue
            shutil.copy2(os.path.join(root, f), target / f)
            total += (target / f).stat().st_size
    return total


def build(out: Path, models: bool) -> dict[str, int]:
    base = Path(sys.base_prefix)
    venv_site = Path(sys.prefix) / "Lib" / "site-packages"
    if base == Path(sys.prefix):
        raise SystemExit("Run this with the project's .venv Python (its packages are what gets shipped).")
    if out.exists():
        shutil.rmtree(out)
    python = out / "python"
    sizes = {}

    # 1. The interpreter: top-level files + DLLs, and the standard library without tests/IDLE/Tk.
    sizes["python"] = copy_tree(base, python, lambda rel, name: rel == "." and name in SKIP_TOP)
    sizes["python"] += copy_tree(base / "Lib", python / "Lib",
                                 lambda rel, name: (rel == "." and name in SKIP_LIB) or
                                 os.path.join(rel, name) in SKIP_LIB)
    # 2. NOVA's packages, exactly as installed and tested in the venv.
    sizes["packages"] = copy_tree(venv_site, python / "Lib" / "site-packages",
                                  lambda rel, name: rel == "." and is_dev_package(name))
    # 3. The backend itself.
    sizes["backend"] = copy_tree(BACKEND / "nova", out / "backend" / "nova")
    # 4. Voice models (whisper cache layout + piper voices); locks are not needed.
    if models:
        source = PROJECT / "data" / "models"
        if not (source / "whisper").is_dir() or not any((source / "piper").glob("*.onnx")):
            raise SystemExit("Voice models missing in data/models - run scripts/download_voice_models.py first.")
        sizes["models"] = copy_tree(source, out / "models", lambda rel, name: name == ".locks")
    return sizes


def verify(out: Path) -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON") and k != "VIRTUAL_ENV"}
    env["PYTHONNOUSERSITE"] = "1"  # never pick up packages from the user's own Python
    result = subprocess.run([str(out / "python" / "python.exe"), "-m", "nova", "--check"], cwd=out / "backend",
                            env=env, capture_output=True, text=True, timeout=300)
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr.strip()[-2000:])
        raise SystemExit("The new runtime cannot load NOVA - see above.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-models", action="store_true")
    args = parser.parse_args()
    sizes = build(args.out.resolve(), models=not args.no_models)
    verify(args.out.resolve())
    for part, size in sizes.items():
        print(f"{part:<9} {size / 1024 ** 2:8.0f} MB")
    print(f"{'total':<9} {sum(sizes.values()) / 1024 ** 2:8.0f} MB -> {args.out}")


if __name__ == "__main__":
    main()
