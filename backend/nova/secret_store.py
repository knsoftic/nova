"""API keys and other secrets: encrypted at rest with Windows DPAPI, never returned to the UI.

DPAPI ties the ciphertext to this Windows user account, so a copied database is useless elsewhere.
Only a masked form (last 4 characters) is ever shown; values never enter logs.
"""

from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes

from .db import Database

PREFIX = "secret:"
KNOWN_SECRETS = {"brave_api_key"}


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    if sys.platform != "win32":  # tests on other platforms: reversible encoding only
        return data
    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))  # kept referenced until the call returns
    blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    fn = crypt32.CryptProtectData if encrypt else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("DPAPI failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def protect(data: bytes) -> str:
    """Encrypt bytes for this Windows user (e.g. a Multi-PC link key) -> text for the database."""
    return base64.b64encode(_dpapi(data, encrypt=True)).decode("ascii")


def unprotect(text: str) -> bytes | None:
    try:
        return _dpapi(base64.b64decode(text), encrypt=False)
    except (OSError, ValueError):
        return None  # e.g. database copied from another Windows account


def set_secret(db: Database, name: str, value: str) -> None:
    if name not in KNOWN_SECRETS:
        raise KeyError(name)
    db.set_setting(PREFIX + name, base64.b64encode(_dpapi(value.encode("utf-8"), encrypt=True)).decode("ascii"))


def get_secret(db: Database, name: str) -> str | None:
    raw = db.get_setting(PREFIX + name)
    if not raw:
        return None
    try:
        return _dpapi(base64.b64decode(raw), encrypt=False).decode("utf-8")
    except (OSError, ValueError):
        return None  # e.g. database copied from another Windows account


def delete_secret(db: Database, name: str) -> None:
    db.set_setting(PREFIX + name, "")


def masked(value: str | None) -> str | None:
    return None if not value else "••••" + value[-4:]
