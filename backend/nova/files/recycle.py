"""Delete = move to the Recycle Bin. NOVA never deletes permanently (the user can restore from the Bin).

SHFileOperation with FOF_ALLOWUNDO sends items to the Recycle Bin. FOF_WANTNUKEWARNING makes Windows ask
the user before it would ever destroy an item permanently (e.g. too big for the Bin), instead of silently
deleting it. Only fixed drives have a Recycle Bin, so removable/network drives are refused up front.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
FOF_WANTNUKEWARNING = 0x4000
DRIVE_FIXED = 3


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def has_recycle_bin(path: Path) -> bool:
    if sys.platform != "win32":
        return False
    drive = path.anchor or str(path)[:3]
    return ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive)) == DRIVE_FIXED


def send_to_recycle_bin(path: Path) -> None:
    """Raises OSError if Windows did not recycle the item."""
    if sys.platform != "win32":
        raise OSError("Recycle Bin sirf Windows par hai")
    if not has_recycle_bin(path):
        raise OSError("Is drive par Recycle Bin nahi hai")
    source = ctypes.create_unicode_buffer(str(path) + "\0")  # double-NUL terminated list of one path
    op = _SHFILEOPSTRUCTW(
        hwnd=None,
        wFunc=FO_DELETE,
        pFrom=ctypes.cast(source, wintypes.LPCWSTR),
        pTo=None,
        fFlags=FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI | FOF_WANTNUKEWARNING,
    )
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0 or op.fAnyOperationsAborted:
        raise OSError(f"Windows ne Recycle Bin mein nahi bheja (code {result:#x})")
