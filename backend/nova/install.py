"""Installed NOVA (Phase 12): where things are, Windows startup registration, Ollama/model readiness for the setup.

The desktop app registers "start with Windows" itself (HKCU Run value "NOVA"); the backend only reads it, so the
Admin self-test and Settings can show whether the setting and Windows agree.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .config import PROJECT_ROOT, Settings

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "NOVA"


def startup_command() -> str | None:
    """The command Windows runs for NOVA at login, or None when NOVA is not registered."""
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE)
            return str(value)
    except OSError:
        return None


def ollama_path() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    default = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    return str(default) if default.is_file() else None


def voice_models(settings: Settings) -> dict[str, bool]:
    models = settings.models_dir
    return {"whisper": any((models / "whisper").glob("**/model.bin")),
            "piper": any((models / "piper").glob("*.onnx"))}


def install_info(settings: Settings) -> dict[str, Any]:
    command = startup_command()
    return {
        "version": __version__,
        "packaged": settings.packaged,
        "program_dir": str(PROJECT_ROOT),
        "data_dir": str(settings.data_dir),
        "models_dir": str(settings.models_dir),
        "python": f"{platform.python_version()} ({Path(sys.executable).parent})",
        "startup_registered": command is not None,
        "startup_command": command,
        "voice_models": voice_models(settings),
        "logs_md": settings.logs_path is not None,
    }
