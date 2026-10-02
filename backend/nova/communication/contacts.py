"""NOVA's own contact list: who the Communication Agent may message, added by the user only.

NOVA never searches the user's WhatsApp chats or address books for a recipient: a message goes only to a
number/email the user saved here (or typed in the command), so it cannot reach the wrong "Ali".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

EMAIL = re.compile(r"^[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+$")
DEFAULT_COUNTRY = "92"  # Pakistan: "0300 1234567" -> 92 300 1234567


@dataclass
class Contact:
    name: str
    phone: str | None = None  # international digits without "+", e.g. 923001234567
    email: str | None = None
    id: int | None = None


def normalize_phone(raw: str, country: str = DEFAULT_COUNTRY) -> str | None:
    digits = re.sub(r"[^\d+]", "", raw.strip())
    if digits.startswith("+"):
        digits = digits[1:]
    elif digits.startswith("00"):
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = country + digits[1:]
    return digits if re.fullmatch(r"\d{10,15}", digits) else None


def show_phone(digits: str | None) -> str:
    if not digits:
        return ""
    if digits.startswith("92") and len(digits) == 12:
        return f"+92 {digits[2:5]} {digits[5:]}"
    return f"+{digits}"


def valid_email(value: str) -> str | None:
    value = value.strip().strip("<>").lower()
    return value if EMAIL.match(value) else None


def find_contact(name: str, contacts: list[Contact]) -> Contact | list[Contact] | None:
    """Exact name first; then a unique contact whose name starts with / contains the words."""
    wanted = " ".join(name.lower().split())
    exact = [c for c in contacts if c.name.lower() == wanted]
    if exact:
        return exact[0]
    for tier in ([c for c in contacts if c.name.lower().startswith(wanted)],
                 [c for c in contacts if wanted in c.name.lower()]):
        if len(tier) == 1:
            return tier[0]
        if tier:
            return tier
    return None
