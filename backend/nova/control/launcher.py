"""Launch installed applications and verify that a window actually appeared.

Only apps found by System Discovery can be launched, by their Start-menu AppID or discovered
executable - never an arbitrary path or command line coming from the user or the AI model.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Callable, Literal

from ..discovery.models import AppEntry
from . import windows as win

CREATE_NO_WINDOW = 0x08000000
VERIFY_TIMEOUT_S = 15.0

Outcome = Literal["opened", "already_open", "launched_unverified", "failed"]


@dataclass
class LaunchResult:
    outcome: Outcome
    window_title: str | None = None
    seconds: float = 0.0
    error: str | None = None

    @property
    def verified(self) -> bool:
        return self.outcome in ("opened", "already_open")


def _start(app: AppEntry) -> None:
    if app.app_id:
        # shell:AppsFolder starts any Start-menu entry (desktop and Store apps) exactly like a click.
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app.app_id}"], creationflags=CREATE_NO_WINDOW)
    elif app.executable and os.path.isfile(app.executable):
        os.startfile(app.executable)  # noqa: S606 - path comes from the discovered app catalog only
    else:
        raise FileNotFoundError(f"{app.name}: launch karne ka tareeqa nahi mila")


def launch(
    app: AppEntry,
    timeout: float = VERIFY_TIMEOUT_S,
    starter: Callable[[AppEntry], None] = _start,
    list_windows: Callable[[], list[win.WindowInfo]] = win.list_windows,
    foreground: Callable[[], win.WindowInfo | None] = win.foreground,
) -> LaunchResult:
    started = time.monotonic()
    before = {w.hwnd for w in list_windows()}
    already = [w for w in list_windows() if not w.is_nova and win.window_matches(w, app.name, app.executable)]
    try:
        starter(app)
    except (OSError, FileNotFoundError) as exc:
        return LaunchResult("failed", error=str(exc), seconds=time.monotonic() - started)

    deadline = started + timeout
    while time.monotonic() < deadline:
        time.sleep(0.4)
        for w in list_windows():
            if w.is_nova or not win.window_matches(w, app.name, app.executable):
                continue
            if w.hwnd not in before:
                return LaunchResult("opened", w.title, time.monotonic() - started)
        fg = foreground()
        # Single-instance apps just bring their existing window forward.
        if already and fg and any(fg.hwnd == w.hwnd for w in already):
            return LaunchResult("already_open", fg.title, time.monotonic() - started)
    if already:
        return LaunchResult("already_open", already[0].title, time.monotonic() - started)
    return LaunchResult("launched_unverified", seconds=time.monotonic() - started)
