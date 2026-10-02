"""Tone adaptation: how NOVA phrases and speaks a reply, from the estimate and the user's chosen reply style.

The facts never change - what was done, what was verified, what failed. Only the wrapping does: a calm apology and a
clear next step when the user seems frustrated, fewer words when they are in a hurry (or asked for short replies),
an example when they seem confused.
"""

from __future__ import annotations

import re

from .estimator import Estimate

STYLES = ("normal", "brief", "calm", "helpful", "detailed")
REPLY_STYLES = ("auto", "short", "detailed")
# Added to the local model's prompt for "chat" answers.
LLM_HINTS = {
    "brief": "The user is in a hurry: answer in one short sentence.",
    "calm": "The user seems frustrated: answer calmly and directly in one or two short sentences, no jokes, no "
            "exclamation marks.",
    "helpful": "The user seems unsure: explain simply in two or three short sentences, with one small example.",
    "detailed": "The user likes detailed answers: you may use up to 4 sentences.",
}
VERIFY_NOTE = re.compile(r"\s*\((?:Verify|verify)[^()]*(?:\([^()]*\)[^()]*)*\)")
# How-to hints ("Chalane ke liye kahein: \"work start karo\".") - one sentence each.
HINT_SENTENCE = re.compile(r"(?:^|(?<=[.!?\n]))[ \t]*(?:Chalane ke liye kahein|Agli dafa bas|Maslan:)[^\n]*?\.(?=\s|$)",
                           re.MULTILINE)
SPEECH_CHARS = 160
EXAMPLES = {
    "files": "\"Downloads mein pdf files dhoondo\", \"notes.txt kholo\"",
    "apps": "\"Chrome kholo\", \"VS Code band karo\"",
    "web": "\"YouTube kholo\", \"solar energy par research karo\"",
    "memory": "\"yaad rakho ke ...\", \"aaj kya kya kiya\"",
    "settings": "\"volume 30 karo\", \"dark mode on karo\"",
    "general": "\"Chrome kholo\", \"RAM batao\", \"Downloads mein pdf dhoondo\"",
}
AREA = [
    ("files", re.compile(r"file|folder|organize|undo")),
    ("apps", re.compile(r"app|window|screen|shortcut|type_text|mouse")),
    ("web", re.compile(r"web|website|browser|research|download|page")),
    ("memory", re.compile(r"memory|fact|history|workflow")),
    ("settings", re.compile(r"setting")),
]


def choose_style(estimate: Estimate, preference: str) -> str:
    """preference: auto | short | detailed (Settings, or "chhote jawab diya karo")."""
    state = estimate.state
    if preference == "short":
        return "calm" if state == "frustrated" else "brief"
    if preference == "detailed":
        return "helpful" if state == "confused" else "detailed"
    return {"frustrated": "calm", "hurried": "brief", "tired": "brief", "confused": "helpful"}.get(state, "normal")


def compact(text: str) -> str:
    """Fewer words on screen: verification notes become a check mark, how-to hints are dropped."""
    text = VERIFY_NOTE.sub(" ✓", text)
    text = HINT_SENTENCE.sub("", text)
    text = re.sub(r"\n\s*✓", " ✓", text)  # a check mark left alone on a line belongs to the line before
    return re.sub(r"[ \t]+\n", "\n", text).strip()


def _first_lines(text: str, limit: int = SPEECH_CHARS) -> str:
    plain = compact(text).replace(" ✓", "")
    lines = [ln.strip() for ln in plain.splitlines() if ln.strip()]
    spoken = " ".join(lines[:3])
    if len(spoken) <= limit:
        return spoken
    cut = max(spoken.rfind(mark, 0, limit) for mark in (".", "!", "?", "۔"))
    return spoken[: cut + 1] if cut > limit // 3 else spoken[:limit].rsplit(" ", 1)[0] + "..."


def examples_for(intents: list[str]) -> str:
    joined = " ".join(intents)
    area = next((name for name, pattern in AREA if pattern.search(joined)), "general")
    return EXAMPLES[area]


def shape(response: str, style: str, *, outcome: str, intents: list[str], simple: bool) -> tuple[str, str | None]:
    """(text shown on screen, text to speak - None means speak the screen text)."""
    failed = outcome in ("failed", "not_understood")
    if style == "calm":
        text = compact(response)
        if failed and not text.startswith(("Maaf", "Theek hai")):
            text = "Maaf kijiye. " + text
        if outcome == "not_understood":
            text += f"\nSeedha aise kahein, maslan: {EXAMPLES['general']}."
        elif outcome == "failed":
            text += "\nChahein to \"dobara karo\" kahein — wajah Activity Log mein hai."
        return text, _first_lines(text)
    if style == "brief":
        text = compact(response)
        return text, _first_lines(text)
    if style == "helpful":
        text = response
        if failed or len(response) < 300:
            text += f"\n(Misaal: {examples_for(intents)})"
        return text, None
    if style == "normal" and simple and outcome == "done":
        return response, _first_lines(response)  # a plain command: say that it is done, not every detail
    return response, None
