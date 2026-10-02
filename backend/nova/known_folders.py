"""Real locations of the user's Documents/Downloads/Desktop (they may be redirected, e.g. to OneDrive)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Registry value names under "User Shell Folders" (Downloads has no friendly name, only its GUID).
_SHELL_FOLDER_VALUES = {
    "desktop": "Desktop",
    "documents": "Personal",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "pictures": "My Pictures",
    "music": "My Music",
    "videos": "My Video",
}


def known_folder(name: str) -> Path:
    fallback = Path.home() / {"documents": "Documents", "downloads": "Downloads"}.get(name, name.capitalize())
    if sys.platform != "win32":
        return fallback
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            value, _ = winreg.QueryValueEx(key, _SHELL_FOLDER_VALUES[name])
        return Path(os.path.expandvars(value))
    except (OSError, KeyError):
        return fallback


def nova_folder(base: str, *parts: str) -> Path:
    """A NOVA-owned folder inside a known folder (e.g. Documents\\NOVA\\Research), created on demand."""
    path = known_folder(base).joinpath("NOVA", *parts)
    path.mkdir(parents=True, exist_ok=True)
    return path
