"""Deterministic intent parser for Urdu, Roman Urdu, Hindi and English.

This is the offline fallback provider. An LLM provider (Ollama) will replace it as the
primary brain in Phase 4, but this one stays available when no model is installed.
"""

from __future__ import annotations

import re

from ..language import detect_language
from .base import AIProvider, Intent

WAKE_WORD = re.compile(r"^\s*(?:hey|hi|ok|ay|ae|اے|ہے)?\s*(?:nova|نووا|नोवा)[\s,!.:-]*", re.IGNORECASE)

GREETING = re.compile(
    r"^(?:hello|hi|hey|salam|salaam|assalam[\s-]?o[\s-]?alaikum|aoa|namaste|namaskar|"
    r"السلام علیکم|سلام|नमस्ते)\b",
    re.IGNORECASE,
)

HELP = re.compile(
    r"\b(?:help|madad|kya kar sakte ho|kya kar sakti ho|what can you do)\b|مدد|کیا کر سکتے|मदद",
    re.IGNORECASE,
)

SYSTEM_INFO = re.compile(
    r"\b(?:system|ram|cpu|memory|storage|disk|windows version|profile)\b|سسٹم|सिस्टम",
    re.IGNORECASE,
)

CREATE_FOLDER = [
    re.compile(r"\b(?:create|make|new)\s+(?:a\s+)?folder(?:\s+(?:named|called)\s+(?P<name>.+))?$", re.IGNORECASE),
    re.compile(r"^(?P<name>.+?)\s+(?:naam\s+ka\s+)?folder\s+(?:create|bana)\s*(?:karo|kar do|kardo|do|o)?$", re.IGNORECASE),
    re.compile(r"\bfolder\s+(?:create|bana)\s*(?:karo|kar do|kardo|do|o)?\b", re.IGNORECASE),
    re.compile(r"فولڈر\s+بناؤ|फ़ोल्डर\s+बनाओ|फोल्डर\s+बनाओ"),
]

WEB_SEARCH = [
    # Order matters: the bare "X mein search karo" form must win before the query-capturing form.
    re.compile(r"^(?:.+?\s+(?:mein|me)\s+)?search\s+(?:karo|kar do|kardo|kijiye|karein)$", re.IGNORECASE),
    re.compile(r"^(?:.+?\s+(?:mein|me|par|pe)\s+)?(?P<query>.+?)\s+(?:ki\s+|ko\s+)?search\s+(?:karo|kar do|kardo|kijiye|karein)$", re.IGNORECASE),
    re.compile(r"\b(?:search|google)\s+(?:for\s+)?(?P<query>.+)$", re.IGNORECASE),
]

RUN_WORKFLOW = re.compile(
    r"^(?:mera\s+|meri\s+|my\s+)?(?P<name>work(?:\s+environment)?|kaam)\s+(?:start|shuru)\s*(?:karo|kar do|kardo|kijiye|karein)?$"
    r"|^start\s+(?:my\s+)?(?P<name2>work(?:\s+environment)?)$",
    re.IGNORECASE,
)

OPEN_APP = [
    re.compile(r"^(?:please\s+)?(?:open|launch|start|run)\s+(?P<app>.+?)(?:\s+please)?$", re.IGNORECASE),
    re.compile(
        r"^(?P<app>.+?)\s+(?:(?:open|start|launch|on)\s+(?:karo|kar do|kardo|kijiye|karein|kro)|kholo|khol do|chalao|chala do)$",
        re.IGNORECASE,
    ),
    re.compile(r"^(?P<app>.+?)\s+(?:کھولو|کھول دو|چلاؤ|اوپن کرو|اوپن کر دو)$"),
    re.compile(r"^(?P<app>.+?)\s+(?:खोलो|खोल दो|चलाओ|ओपन करो|ओपन कर दो)$"),
]

FOLDER_DETERMINERS = {"ye", "yeh", "is", "ek", "aik", "naya", "new", "this", "a"}

TRAILING_PUNCT =re.compile(r"[\s.!?۔،,]+$")


def normalize(text: str) -> str:
    text = WAKE_WORD.sub("", text.strip())
    return TRAILING_PUNCT.sub("", text).strip()


def _clean_entity(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"^(?:the|a|an)\s+", "", value.strip(), flags=re.IGNORECASE)
    return value.strip(" \"'") or None


class RuleBasedProvider(AIProvider):
    name = "rule_based"
    is_local = True

    async def detect_intent(self, text: str) -> Intent:
        language = detect_language(text)
        cleaned = normalize(text)

        def make(name: str, confidence: float, **entities: object) -> Intent:
            return Intent(
                name=name,
                confidence=confidence,
                language=language,
                entities={k: v for k, v in entities.items() if v is not None},
                provider=self.name,
            )

        if not cleaned:
            return make("greeting", 0.6)

        if m := RUN_WORKFLOW.search(cleaned):
            return make("run_workflow", 0.8, workflow=(m.group("name") or m.group("name2")).lower())

        for pattern in CREATE_FOLDER:
            if m := pattern.search(cleaned):
                name = _clean_entity(m.groupdict().get("name"))
                if name and name.lower() in FOLDER_DETERMINERS:
                    name = None
                return make("create_folder", 0.8, folder_name=name)

        for pattern in WEB_SEARCH:
            if m := pattern.search(cleaned):
                query = _clean_entity(m.groupdict().get("query"))
                return make("web_search", 0.8, query=query)

        for pattern in OPEN_APP:
            if m := pattern.search(cleaned):
                return make("open_app", 0.85, app=_clean_entity(m.group("app")))

        if SYSTEM_INFO.search(cleaned):
            return make("system_info", 0.75)

        if HELP.search(cleaned):
            return make("help", 0.8)

        if GREETING.search(cleaned):
            return make("greeting", 0.9)

        return make("unknown", 0.0)
