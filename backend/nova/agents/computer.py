"""Computer control for the System Agent: launch/focus/arrange windows, read the screen, shortcuts.

Every action reports how it was verified (spec: never assume success). All Windows access goes
through `Desktop`, so tests can substitute a fake desktop.
"""

from __future__ import annotations

import ctypes
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from ..ai.base import Intent
from ..control import launcher, screen
from ..control import windows as win
from ..control.input import SHORTCUTS, InputController
from ..discovery.apps import find_app
from ..discovery.models import SystemProfile

Verification = Literal["passed", "failed", "not_applicable", "unverified"]

# Words meaning "the window I am working in" rather than an app name.
CURRENT_WINDOW_WORDS = {"window", "ye", "yeh", "is", "isko", "ise", "this", "it", "current", "ye window",
                        "yeh window", "is window", "this window", "current window", "screen"}

SHORTCUT_LABELS = {
    "copy": "copy", "paste": "paste", "cut": "cut", "undo": "undo", "redo": "redo", "select_all": "sab select",
    "save": "save", "new_tab": "naya tab", "close_tab": "tab band", "find": "find", "refresh": "refresh",
    "enter": "Enter", "escape": "Escape", "show_desktop": "desktop", "switch_window": "window switch",
}

LOW_RISK_SHORTCUTS = {"copy", "select_all", "find", "show_desktop", "switch_window", "escape"}
PERMISSION_REQUIRED = {"type_text", "mouse_click", "close_app"}


@dataclass
class ControlOutcome:
    response: str
    action: str
    executed: bool
    verification: Verification
    detail: str | None = None


class Desktop:
    """The real Windows desktop."""

    def __init__(self, inputs: InputController | None = None) -> None:
        self.inputs = inputs or InputController()

    list_windows = staticmethod(win.list_windows)
    last_user_window = staticmethod(win.last_user_window)
    foreground_hwnd = staticmethod(win.foreground_hwnd)
    find_windows = staticmethod(win.find_windows)
    focus = staticmethod(win.focus)
    set_state = staticmethod(win.set_state)
    request_close = staticmethod(win.request_close)
    window_exists = staticmethod(win.exists)
    launch = staticmethod(launcher.launch)
    read_window = staticmethod(screen.read_window)
    save_screenshot = staticmethod(screen.save_screenshot)

    find_element = staticmethod(screen.find_element)
    focused_value = staticmethod(screen.focused_value)

    def hotkey(self, name: str) -> bool:
        return self.inputs.hotkey(name)

    def type_text(self, text: str) -> bool:
        return self.inputs.type_text(text)

    def click(self, x: int, y: int) -> bool:
        return self.inputs.click(x, y)

    def clipboard_sequence(self) -> int:
        return int(ctypes.windll.user32.GetClipboardSequenceNumber()) if sys.platform == "win32" else 0

    def wait_closed(self, hwnd: int, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not win.exists(hwnd):
                return True
            time.sleep(0.2)
        return False


class ComputerAgent:
    def __init__(self, desktop: Desktop, profile: Callable[[], SystemProfile | None], screenshots_dir: Path) -> None:
        self.desktop = desktop
        self.profile = profile
        self.screenshots_dir = screenshots_dir
        # Windows showing NOVA's own UI: never a target for "this window", typing or clicking.
        self.ui_windows: set[int] = set()

    def note_command(self, source: str) -> None:
        """A typed command comes from NOVA's UI, so whatever window is in front right now *is* that UI
        (the Electron app, or a browser during development). Voice commands may come while the user
        works in another app, so they do not mark anything."""
        if source == "text" and (hwnd := self.desktop.foreground_hwnd()):
            self.ui_windows.add(hwnd)

    def _last_user_window(self) -> win.WindowInfo | None:
        return self.desktop.last_user_window(self.ui_windows)

    # ------------------------------------------------------------------ helpers

    def _target_window(self, app: str | None) -> tuple[win.WindowInfo | None, str]:
        """Resolve "Chrome" / "ye window" / nothing to a window. Returns (window, display name)."""
        if not app or app.lower().strip() in CURRENT_WINDOW_WORDS:
            w = self._last_user_window()
            return w, (w.title if w else "window")
        entry = None
        profile = self.profile()
        if profile and (match := find_app(profile.apps, app)):
            entry = match.app
        name = entry.name if entry else app
        windows = self.desktop.find_windows(name, entry.executable if entry else None)
        return (windows[0] if windows else None), name

    # ------------------------------------------------------------------ actions

    def describe_target(self, intent: Intent) -> tuple[str | None, str | None]:
        """Title and process of the window an action would affect (shown in the permission question)."""
        app = intent.entities.get("app") if intent.name == "close_app" else None
        window, _name = self._target_window(str(app) if app else None)
        return (window.title, window.process) if window else (None, None)

    def run(self, intent: Intent, approved: bool = False) -> ControlOutcome:
        """`approved` is set only by the orchestrator after the Permission Engine said yes."""
        e = intent.entities
        if intent.name in PERMISSION_REQUIRED or (intent.name == "keyboard_shortcut"
                                                  and e.get("keys") not in LOW_RISK_SHORTCUTS):
            if not approved:
                # Defence in depth: even a direct call cannot perform a risky action without approval.
                raise PermissionError(f"{intent.name} requires the user's permission")
            match intent.name:
                case "type_text":
                    return self.type_text(str(e.get("text") or ""))
                case "mouse_click":
                    return self.click_element(str(e.get("target") or ""))
                case "close_app":
                    return self.close_app(e.get("app"))
        match intent.name:
            case "open_app":
                return self.open_app(str(e.get("app") or ""))
            case "focus_app":
                return self.focus_app(e.get("app"))
            case "window_control":
                return self.window_control(str(e.get("action") or "minimize"), e.get("app"))
            case "read_screen":
                return self.read_screen(e.get("app"))
            case "screenshot":
                return self.screenshot()
            case "keyboard_shortcut":
                return self.shortcut(str(e.get("keys") or ""))
        raise ValueError(f"Not a computer-control intent: {intent.name}")

    def open_app(self, query: str) -> ControlOutcome:
        if not query:
            return ControlOutcome("Kaun si application kholni hai?", "launch_app", False, "not_applicable")
        profile = self.profile()
        match = find_app(profile.apps, query) if profile else None
        if not match:
            return ControlOutcome(f"Mujhe is PC par \"{query}\" nahi mila, is liye open nahi kar sakta. Kya naam sahi hai?",
                                  "launch_app", False, "not_applicable")
        app = match.app
        result = self.desktop.launch(app)
        if result.outcome == "opened":
            return ControlOutcome(f"{app.name} khul gaya hai. (Verify: window \"{result.window_title}\" "
                                  f"{result.seconds:.1f}s mein nazar aayi.)", "launch_app", True, "passed", result.window_title)
        if result.outcome == "already_open":
            return ControlOutcome(f"{app.name} pehle se khula tha, use saamne la diya.", "launch_app", True, "passed",
                                  result.window_title)
        if result.outcome == "launched_unverified":
            return ControlOutcome(f"{app.name} chalane ki command de di, lekin {result.seconds:.0f} second mein uski window "
                                  "nazar nahi aayi. Shayad abhi load ho raha hai — screen check kar lein.",
                                  "launch_app", True, "failed")
        return ControlOutcome(f"{app.name} open nahi ho saka: {result.error}", "launch_app", False, "failed", result.error)

    def focus_app(self, app: str | None) -> ControlOutcome:
        window, name = self._target_window(app)
        if window is None:
            hint = " Pehle use kholna ho to kahein: \"" + name + " kholo\"." if app else ""
            return ControlOutcome(f"{name} ki koi khuli window nahi mili.{hint}", "focus_window", False, "not_applicable")
        ok = self.desktop.focus(window.hwnd)
        if ok:
            return ControlOutcome(f"{name} saamne aa gaya hai.", "focus_window", True, "passed", window.title)
        return ControlOutcome(f"{name} ko saamne lane ki koshish ki, lekin Windows ne focus nahi diya. "
                              "Taskbar se khol lein.", "focus_window", True, "failed", window.title)

    def window_control(self, action: str, app: str | None) -> ControlOutcome:
        if action == "show_desktop":
            ok = self.desktop.hotkey("show_desktop")
            return ControlOutcome("Sab windows chhoti kar ke desktop dikha diya." if ok else "Desktop nahi dikha saka.",
                                  "show_desktop", ok, "unverified" if ok else "failed")
        window, name = self._target_window(app)
        if window is None:
            return ControlOutcome(f"{name} ki koi khuli window nahi mili.", f"window_{action}", False, "not_applicable")
        ok = self.desktop.set_state(window.hwnd, action)
        label = {"minimize": "chhoti (minimize)", "maximize": "bari (maximize)", "restore": "normal size"}[action]
        if ok:
            return ControlOutcome(f"{name} ki window {label} kar di.", f"window_{action}", True, "passed", window.title)
        return ControlOutcome(f"{name} ki window {label} karne ki koshish ki, lekin tasdeeq nahi hui.",
                              f"window_{action}", True, "failed", window.title)

    def read_screen(self, app: str | None) -> ControlOutcome:
        window, name = self._target_window(app)
        if window is None:
            return ControlOutcome("Koi window nahi mili jise parh sakoon.", "read_screen", False, "not_applicable")
        reading = self.desktop.read_window(window.hwnd, window.title, window.process)
        lines = [line for line in reading.text_lines if len(line.strip()) > 2][:10]
        parts = [f"\"{window.title}\" window ({window.process.removesuffix('.exe')}):"]
        if lines:
            parts.append("Likha hai: " + " | ".join(lines))
        elif not reading.ocr_available:
            parts.append("Text parhne wala Windows OCR available nahi.")
        else:
            parts.append("Koi saaf text nazar nahi aaya (window minimize to nahi?).")
        buttons = [el.name for el in reading.elements if el.kind in ("button", "menuitem", "tabitem", "hyperlink")][:8]
        fields = [el.name for el in reading.elements if el.kind in ("edit", "combobox")][:4]
        if buttons:
            parts.append("Buttons/tabs: " + ", ".join(buttons))
        if fields:
            parts.append("Likhne ki jagah: " + ", ".join(fields))
        return ControlOutcome("\n".join(parts), "read_screen", True, "not_applicable", window.title)

    def screenshot(self) -> ControlOutcome:
        path = self.desktop.save_screenshot(self.screenshots_dir)
        ok = path.exists() and path.stat().st_size > 0
        if ok:
            return ControlOutcome(f"Screenshot le liya: {path}", "screenshot", True, "passed", str(path))
        return ControlOutcome("Screenshot save nahi ho saka.", "screenshot", True, "failed")

    def shortcut(self, keys: str) -> ControlOutcome:
        if keys not in SHORTCUTS:
            return ControlOutcome("Ye keyboard shortcut mujhe maloom nahi.", "keyboard_shortcut", False, "not_applicable")
        label = SHORTCUT_LABELS.get(keys, keys)
        # The command was typed in NOVA, so first return focus to the window the user was working in.
        window = self._last_user_window()
        if keys not in ("show_desktop", "switch_window"):
            if window is None or not self.desktop.focus(window.hwnd):
                return ControlOutcome(f"{label} ke liye koi window saamne nahi la saka.", f"shortcut_{keys}", False, "failed")
        before = self.desktop.clipboard_sequence()
        ok = self.desktop.hotkey(keys)
        where = f" ({window.title})" if window and keys not in ("show_desktop", "switch_window") else ""
        if not ok:
            return ControlOutcome(f"{label} nahi ho saka.", f"shortcut_{keys}", False, "failed")
        if keys in ("copy", "cut"):
            time.sleep(0.3)
            if self.desktop.clipboard_sequence() != before:
                return ControlOutcome(f"{label} ho gaya{where}. Clipboard update ho gaya.", f"shortcut_{keys}", True,
                                      "passed")
            return ControlOutcome(f"{label} dabaya{where}, lekin clipboard nahi badla — shayad kuch select nahi tha.",
                                  f"shortcut_{keys}", True, "failed")
        return ControlOutcome(f"{label} kar diya{where}.", f"shortcut_{keys}", True, "unverified")

    # ------------------------------------------------------------------ actions that need permission

    def type_text(self, text: str) -> ControlOutcome:
        if not text:
            return ControlOutcome("Kya likhna hai?", "type_text", False, "not_applicable")
        window = self._last_user_window()
        if window is None or not self.desktop.focus(window.hwnd):
            return ControlOutcome("Likhne ke liye koi window saamne nahi la saka.", "type_text", False, "failed")
        if not self.desktop.type_text(text):
            return ControlOutcome(f"{window.title} mein likhne mein masla aaya.", "type_text", False, "failed")
        time.sleep(0.2)
        value = self.desktop.focused_value()
        if value is not None and text.strip() in value:
            return ControlOutcome(f"{window.title} mein likh diya. (Verify: text field mein nazar aa raha hai.)",
                                  "type_text", True, "passed", window.title)
        return ControlOutcome(f"{window.title} mein likh diya. Ye app text wapas parhne nahi deti, is liye ek nazar "
                              "dekh lein.", "type_text", True, "unverified", window.title)

    def click_element(self, label: str) -> ControlOutcome:
        if not label:
            return ControlOutcome("Kis cheez par click karna hai?", "mouse_click", False, "not_applicable")
        window = self._last_user_window()
        if window is None:
            return ControlOutcome("Koi window nahi mili.", "mouse_click", False, "not_applicable")
        status, element = self.desktop.find_element(window.hwnd, label)
        if status == "not_found" or element is None:
            return ControlOutcome(f"{window.title} mein \"{label}\" naam ka button/link nahi mila, is liye click nahi kiya.",
                                  "mouse_click", False, "failed")
        if status == "invoked":
            # Accessibility "Invoke" presses the control directly - no mouse movement needed.
            return ControlOutcome(f"\"{element.name}\" daba diya ({window.title}).", "mouse_click", True, "unverified",
                                  element.name)
        if not self.desktop.focus(window.hwnd) or not self.desktop.click(element.x, element.y):
            return ControlOutcome(f"\"{element.name}\" par click nahi ho saka.", "mouse_click", False, "failed")
        return ControlOutcome(f"\"{element.name}\" par click kar diya ({window.title}).", "mouse_click", True,
                              "unverified", element.name)

    def close_app(self, app: str | None) -> ControlOutcome:
        window, name = self._target_window(str(app) if app else None)
        if window is None:
            return ControlOutcome(f"{name} ki koi khuli window nahi mili.", "close_app", False, "not_applicable")
        self.desktop.request_close(window.hwnd)
        if self.desktop.wait_closed(window.hwnd):
            return ControlOutcome(f"{name} band ho gaya. (Verify: window ab nahi hai.)", "close_app", True, "passed",
                                  window.title)
        return ControlOutcome(f"{name} ko band karne ka kaha, lekin window abhi khuli hai — shayad save karne ka pooch "
                              "rahi hai. Aap khud dekh lein.", "close_app", True, "failed", window.title)
