"""Conversation history: searchable records of what the user asked and what NOVA did (date, time, request, response,
permission, action, result, error, completion), kept for the number of days the user chose."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from .facts import STOPWORDS, short_date

PERIODS = ("today", "yesterday", "week", "month", "all")
RETENTION_DAYS = (30, 90, 365, 0)  # 0 = keep until the user deletes it
PERIOD_WORDS = [
    ("today", re.compile(r"\b(?:aaj|today)\b", re.IGNORECASE)),
    ("before_yesterday", re.compile(r"\bparson\b", re.IGNORECASE)),
    ("yesterday", re.compile(r"\b(?:kal|yesterday)\b", re.IGNORECASE)),
    ("week", re.compile(r"\b(?:hafte|hafta|week|7\s+din)\b", re.IGNORECASE)),
    ("month", re.compile(r"\b(?:mahine|mahina|month|30\s+din)\b", re.IGNORECASE)),
]
LABELS = {"today": "aaj", "yesterday": "kal", "before_yesterday": "parson", "week": "pichle 7 din",
          "month": "pichle 30 din", "all": "", "": ""}
# Words in history questions that are not what the user is looking for ("kal maine kya kaha tha").
QUESTION_WORDS = set("""
maine mainay hamne humne tumne nova kaha kiya kia poocha pucha karwaya kahi baat batao dikhao dhoondo dhundo search
karo talash history purani baatein conversation chat tha thi the aaj kal parson hafte hafta mahine mahina pichle pichli
is week month today yesterday what did said ask asked show find my
""".split())
OUTCOME_WORDS = {"done": "ho gaya", "failed": "nahi hua", "denied": "ijazat nahi mili", "answered": "jawab",
                 "not_understood": "samajh nahi aaya"}


def period_of(text: str) -> str:
    for period, pattern in PERIOD_WORDS:
        if pattern.search(text or ""):
            return period
    return ""


def period_range(period: str, now: datetime) -> tuple[datetime | None, datetime | None]:
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    match period:
        case "today":
            return today, None
        case "yesterday":
            return today - timedelta(days=1), today
        case "before_yesterday":
            return today - timedelta(days=2), today - timedelta(days=1)
        case "week":
            return now - timedelta(days=7), None
        case "month":
            return now - timedelta(days=30), None
    return None, None


def search_terms(query: str) -> list[str]:
    """The words worth matching: "kal maine report ke baare mein kya kaha tha" -> ["report"]."""
    out = []
    for w in re.findall(r"\w+", (query or "").lower()):
        if len(w) >= 3 and w not in STOPWORDS and w not in QUESTION_WORDS and w not in out:
            out.append(w)
    return out[:5]


def outcome(conversation: dict[str, Any], steps: list[dict[str, Any]]) -> str:
    """done | failed | denied | answered | not_understood - the completion status of one request."""
    if conversation.get("status") == "failed":
        return "failed"
    if conversation.get("status") == "not_understood":
        return "not_understood"
    executions = {s["execution_status"] for s in steps}
    verifications = {s["verification_status"] for s in steps}
    if "failed" in executions or "failed" in verifications:
        return "failed"
    if executions & {"not_executed_denied"} and "success" not in executions:
        return "denied"
    if "success" in executions:
        return "done"
    return "answered"


def record(conversation: dict[str, Any], steps: list[dict[str, Any]]) -> dict[str, Any]:
    """One history record with everything the spec asks for."""
    created = conversation["created_at"]
    work = [s for s in steps if s["task_name"].startswith("command")]
    errors = [s["error"] for s in steps if s.get("error")]
    permissions = [s["permission_status"] for s in steps if s["permission_status"] not in ("not_required", "decided")]
    return {
        "task_id": conversation["task_id"],
        "date": created[:10],
        "time": created[11:19],
        "source": conversation["source"],
        "request": conversation["user_text"],
        "response": conversation["response"],
        "intent": conversation["intent"],
        "actions": [f"{s['agent']}: {s['action']}" for s in work],
        "permission": permissions[-1] if permissions else "not_required",
        "verification": next((s["verification_status"] for s in work if s["verification_status"] in ("passed", "failed")),
                             "not_applicable"),
        "error": errors[0] if errors else None,
        "outcome": outcome(conversation, work),
    }


def line(rec: dict[str, Any]) -> str:
    first = (rec["response"] or "").strip().splitlines()[0] if rec["response"] else ""
    if len(first) > 90:
        first = first[:87].rstrip() + "..."
    when = f"{short_date(rec['date'] + 'T' + rec['time'])} {rec['time'][:5]}"
    return f"- {when} · “{rec['request'][:80]}” → {first} ({OUTCOME_WORDS[rec['outcome']]})"
