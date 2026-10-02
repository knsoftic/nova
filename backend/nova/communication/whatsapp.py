"""WhatsApp Desktop through its official click-to-chat link - no searching through the user's chats.

After the user said "haan":
1. open "whatsapp://send?phone=<number>&text=<message>": WhatsApp opens exactly that number's chat with the
   text already in the message box (nothing is sent yet);
2. bring the WhatsApp window to the front and confirm the box really holds this text (the focused box's
   accessibility value, else OCR of the bottom of the window). If NOVA cannot confirm it, it stops there;
3. press Enter only while WhatsApp is the foreground window;
4. confirm the box is empty again and the text now shows in the chat.
"""

from __future__ import annotations

import os
import re
import time
import winreg
from typing import Callable
from urllib.parse import quote

from ..control import screen
from ..control.windows import WindowInfo

COMPOSER_STRIP = 0.09  # bottom part of the window holding the message box


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", text.lower())


def click_to_chat_url(phone: str, text: str) -> str:
    return f"whatsapp://send?phone={phone}&text={quote(text, safe='')}"


class WhatsAppDesktop:
    def __init__(
        self,
        list_windows: Callable[[], list[WindowInfo]],
        focus: Callable[[int], bool],
        foreground_hwnd: Callable[[], int | None],
        press_enter: Callable[[], bool],
        *,
        opener: Callable[[str], None] = os.startfile,
        capture: Callable[[int], object] = screen.capture_window,
        ocr: Callable[[object], list[str]] = screen.ocr,
        focused_value: Callable[[], str | None] = screen.focused_value,
        wait_s: float = 15.0,
        settle_s: float = 2.5,
    ) -> None:
        self._list_windows = list_windows
        self._focus = focus
        self._foreground = foreground_hwnd
        self._press_enter = press_enter
        self._open = opener
        self._capture = capture
        self._ocr = ocr
        self._focused_value = focused_value
        self._wait_s = wait_s
        self._settle_s = settle_s

    @staticmethod
    def installed() -> bool:
        try:
            winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "whatsapp").Close()
            return True
        except OSError:
            return False

    def _window(self) -> WindowInfo | None:
        windows = [w for w in self._list_windows() if "whatsapp" in w.process.lower() and w.title]
        return windows[0] if windows else None

    def open_chat(self, phone: str, text: str) -> WindowInfo | None:
        self._open(click_to_chat_url(phone, text))
        deadline = time.monotonic() + self._wait_s
        window = None
        while time.monotonic() < deadline:
            window = self._window()
            if window is not None:
                break
            time.sleep(0.5)
        if window is None:
            return None
        self._focus(window.hwnd)
        time.sleep(self._settle_s)  # the chat and its message box load
        return window

    def _strip_lines(self, window: WindowInfo, whole: bool = False) -> list[str] | None:
        img = self._capture(window.hwnd)
        if img is None:
            return None
        if not whole:
            w, h = img.size
            img = img.crop((0, int(h * (1 - COMPOSER_STRIP)), w, h))
        try:
            return self._ocr(img)
        except Exception:
            return None

    def composer_holds(self, window: WindowInfo, text: str) -> bool | None:
        """True/False when NOVA can tell; None when it cannot read the message box at all."""
        key = _norm(text)[:24]
        if len(key) < 3:
            return None  # e.g. Urdu script or emoji only: OCR cannot confirm it
        value = self._focused_value()
        if value:
            return key in _norm(value)
        lines = self._strip_lines(window)
        if lines is None:
            return None
        return key in _norm(" ".join(lines))

    def press_send(self, window: WindowInfo) -> bool:
        """Enter goes to WhatsApp only: if it is not the foreground window even after focusing, nothing is pressed."""
        if self._foreground() != window.hwnd:
            self._focus(window.hwnd)
            time.sleep(0.4)
        if self._foreground() != window.hwnd:
            return False
        return self._press_enter()

    def sent_visible(self, window: WindowInfo, text: str) -> bool | None:
        time.sleep(1.5)
        key = _norm(text)[:24]
        still = self.composer_holds(window, text)
        lines = self._strip_lines(window, whole=True)
        if still is None or lines is None:
            return None
        return (not still) and key in _norm(" ".join(lines))
