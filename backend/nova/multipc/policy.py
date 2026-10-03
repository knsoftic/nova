"""What a paired PC may ask THIS PC to do (decided here, on the PC where it would happen).

Admin's choice (Phase 13): information and opening things run directly; tasks that need permission are asked on the
PC that sent them (its user is there); deleting, sending messages and dangerous work never run from another PC.
This is an allow-list: anything not named here is refused, including every future capability until it is added.
"""

from __future__ import annotations

# Words only, information, and opening/showing things (low risk on this PC).
REMOTE_DIRECT = {
    "greeting", "help", "thanks", "chat", "unknown",
    "system_info", "app_check",
    "open_app", "focus_app", "window_control", "open_website", "web_search",
    "open_file", "open_project", "open_settings", "change_setting",
}
# Allowed with permission (asked on the sending PC) when the step needs it on this PC.
REMOTE_ASK = {"close_app", "change_setting", "create_folder", "copy_file", "rename_file", "move_file"}
ALLOWED = REMOTE_DIRECT | REMOTE_ASK

REFUSED = "Ye kaam doosre PC se nahi hota — sirf isi PC par khud kahein"
REFUSED_HIGH = "Khatarnak kaam doosre PC se kabhi nahi hota"


def verdict(intent: str, risk: str) -> str | None:
    """None = allowed (risk decides whether the sender is asked first); otherwise why it is refused."""
    if risk == "high":
        return REFUSED_HIGH
    if risk == "low" and intent in REMOTE_DIRECT | REMOTE_ASK:
        return None
    if risk == "medium" and intent in REMOTE_ASK:
        return None
    return REFUSED
