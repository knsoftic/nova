"""Screen understanding: window capture (even when covered), Windows OCR, UI Automation tree.

Prefers accessibility information (exact names of buttons/fields) and uses OCR for visible text.
Everything runs locally; captures are kept in memory unless the user asks for a screenshot.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
from ctypes import wintypes
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image

log = logging.getLogger("nova.control.screen")

PW_RENDERFULLCONTENT = 0x00000002
UI_ELEMENT_TYPES = {"ButtonControl", "EditControl", "MenuItemControl", "TabItemControl", "HyperlinkControl",
                    "CheckBoxControl", "ComboBoxControl", "ListItemControl", "RadioButtonControl"}
MAX_UI_ELEMENTS = 60
MAX_OCR_LINES = 200


@dataclass
class UiElement:
    kind: str  # button | edit | menuitem | ...
    name: str
    x: int  # centre, screen coordinates
    y: int


@dataclass
class ScreenReading:
    window_title: str
    process: str
    text_lines: list[str] = field(default_factory=list)
    elements: list[UiElement] = field(default_factory=list)
    ocr_available: bool = True


def _gdi() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    """user32/gdi32 with handle-sized types: without them 64-bit handles overflow ctypes' int default."""
    user32, gdi32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
    H = wintypes.HANDLE
    user32.GetWindowDC.argtypes, user32.GetWindowDC.restype = [wintypes.HWND], H
    user32.ReleaseDC.argtypes = [wintypes.HWND, H]
    user32.PrintWindow.argtypes = [wintypes.HWND, H, wintypes.UINT]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.IsIconic.argtypes = [wintypes.HWND]
    gdi32.CreateCompatibleDC.argtypes, gdi32.CreateCompatibleDC.restype = [H], H
    gdi32.CreateCompatibleBitmap.argtypes, gdi32.CreateCompatibleBitmap.restype = [H, ctypes.c_int, ctypes.c_int], H
    gdi32.SelectObject.argtypes, gdi32.SelectObject.restype = [H, H], H
    gdi32.DeleteObject.argtypes = [H]
    gdi32.DeleteDC.argtypes = [H]
    gdi32.GetDIBits.argtypes = [H, H, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    return user32, gdi32


def capture_window(hwnd: int) -> Image.Image | None:
    """Capture a window's content with PrintWindow, so it works even if NOVA is covering it."""
    user32, gdi32 = _gdi()
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0 or user32.IsIconic(hwnd):
        return None
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mem, bmp)
    try:
        if not user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT):
            return None

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]

        header = BITMAPINFOHEADER(biSize=ctypes.sizeof(BITMAPINFOHEADER), biWidth=w, biHeight=-h, biPlanes=1,
                                  biBitCount=32, biCompression=0)
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(header), 0)
        return Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    finally:
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(hwnd, hdc)


def capture_screen() -> Image.Image:
    import mss

    with mss.MSS() as s:
        shot = s.grab(s.monitors[0])  # all monitors
        return Image.frombytes("RGB", shot.size, shot.rgb)


def save_screenshot(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"NOVA_{datetime.now():%Y%m%d_%H%M%S}.png"
    capture_screen().save(path, "PNG")
    return path


async def _ocr_async(img: Image.Image) -> list[str]:
    from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter

    if max(img.size) > OcrEngine.max_image_dimension:
        img.thumbnail((OcrEngine.max_image_dimension, OcrEngine.max_image_dimension))
    r, g, b = img.convert("RGB").split()
    alpha = Image.new("L", img.size, 255)
    writer = DataWriter()
    writer.write_bytes(Image.merge("RGBA", (b, g, r, alpha)).tobytes())  # SoftwareBitmap wants BGRA
    bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.BGRA8, *img.size)
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError("Windows OCR language installed nahi")
    result = await engine.recognize_async(bitmap)
    return [line.text for line in result.lines][:MAX_OCR_LINES]


def ocr(img: Image.Image) -> list[str]:
    return asyncio.run(_ocr_async(img))


def ui_elements(hwnd: int) -> list[UiElement]:
    """Named, interactive controls from the accessibility tree (exact labels, no guessing from pixels)."""
    import uiautomation as auto

    found: list[UiElement] = []
    # UI Automation is COM: each worker thread must initialise it.
    with auto.UIAutomationInitializerInThread():
        root = auto.ControlFromHandle(hwnd)
        for control, _depth in auto.WalkControl(root, maxDepth=12):
            if control.ControlTypeName not in UI_ELEMENT_TYPES or not control.Name:
                continue
            rect = control.BoundingRectangle
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            found.append(UiElement(kind=control.ControlTypeName.removesuffix("Control").lower(),
                                   name=control.Name[:80],
                                   x=(rect.left + rect.right) // 2, y=(rect.top + rect.bottom) // 2))
            if len(found) >= MAX_UI_ELEMENTS:
                break
    return found


def read_window(hwnd: int, title: str, process: str) -> ScreenReading:
    reading = ScreenReading(window_title=title, process=process)
    try:
        reading.elements = ui_elements(hwnd)
    except Exception as exc:  # some apps expose no accessibility tree
        log.info("UI Automation unavailable for %s: %s", process, exc)
    img = capture_window(hwnd)
    if img is not None:
        try:
            reading.text_lines = ocr(img)
        except Exception as exc:
            log.warning("OCR failed: %s", exc)
            reading.ocr_available = False
    return reading
