"""Deterministic intent parser for Urdu, Roman Urdu, Hindi and English.

This is the offline fallback provider. An LLM provider (Ollama) will replace it as the
primary brain in Phase 4, but this one stays available when no model is installed.
"""

from __future__ import annotations

import re

from ..language import detect_language
from .base import AIProvider, Intent

BUILTIN_NAMES = ("nova", "نووا", "नोवा")


def build_wake_pattern(assistant_name: str = "NOVA", wake_word: str = "Hey NOVA") -> re.Pattern[str]:
    """Matches the configured wake word, or '[hey] <name>', at the start of an utterance."""
    names = sorted({re.escape(assistant_name), *BUILTIN_NAMES}, key=len, reverse=True)
    return re.compile(
        rf"^\s*(?:{re.escape(wake_word)}|(?:hey|hi|ok|ay|ae|اے|ہے)?\s*(?:{'|'.join(names)}))(?![\w])[\s,!.:-]*",
        re.IGNORECASE,
    )


WAKE_WORD = build_wake_pattern()

GREETING = re.compile(
    r"^(?:hello|hi|hey|salam|salaam|assalam[\s-]?o[\s-]?alaikum|aoa|namaste|namaskar|"
    r"السلام علیکم|سلام|नमस्ते)\b",
    re.IGNORECASE,
)

HELP = re.compile(
    r"\b(?:help|madad|kya kar sakte ho|kya kar sakti ho|what can you do)\b|مدد|کیا کر سکتے|मदद",
    re.IGNORECASE,
)

# Ordered: the first matching topic wins ("kaun si apps chal rahi hain" is running apps, not installed apps).
SYSTEM_TOPICS: list[tuple[str, re.Pattern[str]]] = [
    (topic, re.compile(pattern, re.IGNORECASE))
    for topic, pattern in [
        ("running", r"chal rah[eiy]|running|khul[ei] hu[ei]|open (?:apps|windows)"),
        ("browsers", r"\bbrowsers?\b|براؤزر|ब्राउज़र"),
        ("apps", r"\b(?:apps?|applications?|softwares?|programs?)\b|ایپس|ایپلیکیشن"),
        ("ram", r"\bram\b|\bmemory\b|ریم|میموری|रैम"),
        ("cpu", r"\bcpu\b|processor|پروسیسر|प्रोसेसर"),
        ("gpu", r"\bgpu\b|graphics?|گرافکس|ग्राफिक्स"),
        ("storage", r"storage|\bdisk\b|\bdrives?\b|hard ?disk|\bspace\b|اسٹوریج|سٹوریج|स्टोरेज"),
        ("windows", r"\bwindows\b|ونڈوز|विंडोज"),
        ("devices", r"\bmic\b|microphone|speakers?|camera|webcam|مائیک|کیمرہ|स्पीकर|कैमरा"),
        ("displays", r"monitors?|displays?|screens?"),
        ("network", r"network|internet|wi-?fi|انٹرنیٹ|इंटरनेट"),
        ("admin", r"\badmin(?:istrator)?\b|permissions?"),
    ]
]

SYSTEM_INFO = re.compile(r"\b(?:system|profile|pc|computer|laptop)\b|سسٹم|सिस्टम|کمپیوٹر", re.IGNORECASE)

RESCAN = re.compile(r"\b(?:re-?scan|scan)\b|اسکین|स्कैन", re.IGNORECASE)

APP_CHECK = [
    re.compile(r"^(?:kya\s+)?(?:mere\s+(?:pc|system|computer|laptop)\s+(?:mein|me|par|pe)\s+)?(?P<app>.+?)\s+installed\s+(?:hai|he|h|hain)\b", re.IGNORECASE),
    re.compile(r"^is\s+(?P<app>.+?)\s+installed\b", re.IGNORECASE),
    re.compile(r"^(?:do\s+i\s+have|have\s+i\s+got)\s+(?P<app>.+?)(?:\s+installed)?$", re.IGNORECASE),
]
NOT_AN_APP = re.compile(r"\b(?:apps?|applications?|softwares?|programs?|kaun|kon|konse|kaunse|which|what|kitn[ei])\b", re.IGNORECASE)

CHANGE_SETTING = re.compile(
    r"\b(?:default|settings?)\b.*\b(?:bana|set|change|badal|make)\b|\b(?:set|make|change)\b.*\bdefault\b",
    re.IGNORECASE,
)


def system_topic(text: str) -> str | None:
    for topic, pattern in SYSTEM_TOPICS:
        if pattern.search(text):
            return topic
    return None

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


def normalize(text: str, wake: re.Pattern[str] = WAKE_WORD) -> str:
    text = wake.sub("", text.strip())
    return TRAILING_PUNCT.sub("", text).strip()


def _clean_entity(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"^(?:the|a|an)\s+", "", value.strip(), flags=re.IGNORECASE)
    return value.strip(" \"'") or None


class RuleBasedProvider(AIProvider):
    name = "rule_based"
    is_local = True

    def __init__(self) -> None:
        self._wake = WAKE_WORD

    def configure_wake(self, assistant_name: str, wake_word: str) -> None:
        self._wake = build_wake_pattern(assistant_name, wake_word)

    async def detect_intent(self, text: str) -> Intent:
        language = detect_language(text)
        cleaned = normalize(text, self._wake)

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

        if CHANGE_SETTING.search(cleaned):
            return make("change_setting", 0.7, request=cleaned)

        for pattern in APP_CHECK:
            if (m := pattern.search(cleaned)) and not NOT_AN_APP.search(m.group("app")):
                return make("app_check", 0.85, app=_clean_entity(m.group("app")))

        if RESCAN.search(cleaned):
            return make("rescan_system", 0.8)

        topic = system_topic(cleaned)
        if topic or SYSTEM_INFO.search(cleaned):
            return make("system_info", 0.8, topic=topic or "summary")

        if HELP.search(cleaned):
            return make("help", 0.8)

        if GREETING.search(cleaned):
            return make("greeting", 0.9)

        return make("unknown", 0.0)
