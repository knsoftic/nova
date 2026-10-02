"""Keyboard and mouse input via SendInput.

These actions change things in other apps (typing, pasting, clicking), so the planner marks them
medium risk: they only run after the user grants permission (Permission Engine, Phase 7).
Windows itself blocks input into elevated (administrator) windows from a normal process.
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from typing import Callable

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE = 0x0001, 0x8000
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010

VK = {
    "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "enter": 0x0D, "tab": 0x09, "esc": 0x1B,
    "backspace": 0x08, "delete": 0x2E, "space": 0x20, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    **{f"f{n}": 0x6F + n for n in range(1, 13)},
    **{chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)},  # letter keys use uppercase ASCII codes
    **{str(d): 0x30 + d for d in range(10)},
}

# Named shortcuts NOVA understands -> key combination.
SHORTCUTS: dict[str, list[str]] = {
    "copy": ["ctrl", "c"],
    "paste": ["ctrl", "v"],
    "cut": ["ctrl", "x"],
    "undo": ["ctrl", "z"],
    "redo": ["ctrl", "y"],
    "select_all": ["ctrl", "a"],
    "save": ["ctrl", "s"],
    "new_tab": ["ctrl", "t"],
    "close_tab": ["ctrl", "w"],
    "find": ["ctrl", "f"],
    "refresh": ["f5"],
    "enter": ["enter"],
    "escape": ["esc"],
    "show_desktop": ["win", "d"],
    "switch_window": ["alt", "tab"],
}

MAX_TYPE_CHARS = 2000


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def key_event(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    i = INPUT(type=INPUT_KEYBOARD)
    i.u.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags)
    return i


def mouse_event(flags: int, dx: int = 0, dy: int = 0) -> INPUT:
    i = INPUT(type=INPUT_MOUSE)
    i.u.mi = MOUSEINPUT(dx=dx, dy=dy, dwFlags=flags)
    return i


def hotkey_events(keys: list[str]) -> list[INPUT]:
    codes = [VK[k.lower()] for k in keys]
    return [key_event(c) for c in codes] + [key_event(c, flags=KEYEVENTF_KEYUP) for c in reversed(codes)]


def text_events(text: str) -> list[INPUT]:
    """Unicode typing (works for Urdu too), independent of the keyboard layout."""
    events: list[INPUT] = []
    for unit in text.encode("utf-16-le").hex(" ", 2).split():
        code = int.from_bytes(bytes.fromhex(unit), "little")
        events += [key_event(scan=code, flags=KEYEVENTF_UNICODE),
                   key_event(scan=code, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
    return events


def click_events(x: int, y: int, screen_w: int, screen_h: int, button: str = "left", double: bool = False) -> list[INPUT]:
    # Absolute coordinates are normalised to 0..65535 across the primary screen.
    nx, ny = round(x * 65535 / max(1, screen_w - 1)), round(y * 65535 / max(1, screen_h - 1))
    down, up = (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP) if button == "left" else (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP)
    events = [mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE, nx, ny)]
    for _ in range(2 if double else 1):
        events += [mouse_event(down), mouse_event(up)]
    return events


def send(events: list[INPUT]) -> int:
    if not events or sys.platform != "win32":
        return 0
    array = (INPUT * len(events))(*events)
    return ctypes.windll.user32.SendInput(len(events), array, ctypes.sizeof(INPUT))


class InputController:
    """Thin facade so agents (and tests) inject input through one place."""

    def __init__(self, sender: Callable[[list[INPUT]], int] = send) -> None:
        self._send = sender

    def hotkey(self, name: str) -> bool:
        keys = SHORTCUTS[name]
        events = hotkey_events(keys)
        return self._send(events) == len(events)

    def type_text(self, text: str) -> bool:
        events = text_events(text[:MAX_TYPE_CHARS])
        sent = 0
        for i in range(0, len(events), 200):  # small batches so slow apps keep up
            sent += self._send(events[i:i + 200])
            time.sleep(0.01)
        return sent == len(events)

    def click(self, x: int, y: int, double: bool = False, button: str = "left") -> bool:
        if sys.platform == "win32":
            w, h = ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
        else:
            w, h = 1920, 1080
        events = click_events(x, y, w, h, button, double)
        return self._send(events) == len(events)
