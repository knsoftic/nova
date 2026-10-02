"""Top-level window management through the Win32 API (enumerate, focus, minimize, maximize, close)."""

from __future__ import annotations

import ctypes
import os
import re
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass

import psutil

IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND

GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9
WM_CLOSE = 0x0010
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002

# NOVA's own windows are never targets of "this window" commands.
OWN_PROCESSES = {"electron.exe", "nova.exe"}
# Shell surfaces that look like windows but are not apps the user means.
IGNORED_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Windows.UI.Core.CoreWindow"}
IGNORED_TITLES = {"Program Manager", "Windows Input Experience", "Settings Sync", ""}

# Words too generic to identify an app by ("Microsoft Edge" should not match every Microsoft window).
GENERIC_WORDS = {"microsoft", "adobe", "google", "the", "app", "application", "cc", "for", "and", "windows", "desktop"}


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    pid: int
    process: str
    class_name: str
    minimized: bool
    maximized: bool

    @property
    def is_nova(self) -> bool:
        return self.process.lower() in OWN_PROCESSES or self.pid == os.getpid()


def _window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _info(hwnd: int) -> WindowInfo | None:
    title = _window_text(hwnd)
    cls = _class_name(hwnd)
    if title in IGNORED_TITLES or cls in IGNORED_CLASSES:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        process = psutil.Process(pid.value).name()
    except (psutil.Error, OSError):
        process = ""
    return WindowInfo(
        hwnd=int(hwnd), title=title, pid=pid.value, process=process, class_name=cls,
        minimized=bool(user32.IsIconic(hwnd)), maximized=bool(user32.IsZoomed(hwnd)),
    )


def list_windows() -> list[WindowInfo]:
    """Visible, titled, app-level windows in z-order (topmost first)."""
    if not IS_WINDOWS:
        return []
    found: list[WindowInfo] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, GW_OWNER):
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        if info := _info(hwnd):
            found.append(info)
        return True

    user32.EnumWindows(callback, 0)
    return found


def foreground() -> WindowInfo | None:
    hwnd = user32.GetForegroundWindow() if IS_WINDOWS else None
    return _info(hwnd) if hwnd else None


def foreground_hwnd() -> int | None:
    hwnd = user32.GetForegroundWindow() if IS_WINDOWS else None
    return int(hwnd) if hwnd else None


def last_user_window(exclude: set[int] | None = None) -> WindowInfo | None:
    """The window the user was working in before talking to NOVA (topmost non-NOVA window).

    `exclude` holds windows known to host NOVA's UI (e.g. a browser showing it during development).
    """
    exclude = exclude or set()
    return next((w for w in list_windows() if not w.is_nova and w.hwnd not in exclude), None)


def name_tokens(name: str) -> list[str]:
    tokens = [t for t in re.findall(r"[a-z0-9]+", name.lower()) if len(t) >= 3 and t not in GENERIC_WORDS]
    return tokens or [t for t in re.findall(r"[a-z0-9]+", name.lower()) if len(t) >= 2]


def window_matches(window: WindowInfo, app_name: str, executable: str | None = None) -> bool:
    if executable and window.process.lower() == os.path.basename(executable).lower():
        return True
    title, process = window.title.lower(), window.process.lower().removesuffix(".exe")
    return any(t in title or t == process for t in name_tokens(app_name))


def find_windows(app_name: str, executable: str | None = None) -> list[WindowInfo]:
    return [w for w in list_windows() if not w.is_nova and window_matches(w, app_name, executable)]


def focus(hwnd: int, timeout: float = 2.0) -> bool:
    """Bring a window to the front. Windows blocks focus-stealing, so a brief ALT tap is used first
    (the documented way an app that just received input may hand focus over)."""
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.05)
    return False


def set_state(hwnd: int, action: str) -> bool:
    """action: minimize | maximize | restore. Returns True when the new state is confirmed."""
    command = {"minimize": SW_MINIMIZE, "maximize": SW_MAXIMIZE, "restore": SW_RESTORE}[action]
    user32.ShowWindow(hwnd, command)
    time.sleep(0.25)
    if action == "minimize":
        return bool(user32.IsIconic(hwnd))
    if action == "maximize":
        return bool(user32.IsZoomed(hwnd))
    return not user32.IsIconic(hwnd) and not user32.IsZoomed(hwnd)


def request_close(hwnd: int) -> None:
    """Polite close (like clicking X): the app can still ask to save. Never force-kills."""
    user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def exists(hwnd: int) -> bool:
    return bool(user32.IsWindow(hwnd))
