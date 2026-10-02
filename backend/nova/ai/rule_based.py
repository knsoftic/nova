"""Deterministic intent parser for Urdu, Roman Urdu, Hindi and English.

This is the offline fallback provider. An LLM provider (Ollama) will replace it as the
primary brain in Phase 4, but this one stays available when no model is installed.
"""

from __future__ import annotations

import re

from ..language import detect_language
from .base import AIProvider, ConversationTurn, Intent, Understanding

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
        # Needs both an app word and a "running/open" word, so "zindagi kaisi chal rahi hai" is not a system query.
        ("running", r"^(?=.*\b(?:apps?|applications?|programs?|softwares?|windows)\b)(?=.*(?:chal rah|running|khul[ei]|\bopen\b))"),
        # Urdu-script forms include how Whisper spells English tech words ("آر ایم" = RAM, "وندوز" = Windows).
        ("browsers", r"\bbrowsers?\b|براؤزر|براوزر|ब्राउज़र"),
        ("apps", r"\b(?:apps?|applications?|softwares?|programs?)\b|ایپس|ایپلیکیشن|ایپلیکیشنز"),
        ("ram", r"\bram\b|\bmemory\b|ریم|آر\s*ایم|میموری|मेमोरी|रैम|आर\s*एम"),
        ("cpu", r"\bcpu\b|processor|پروسیسر|پراسیسر|سی\s*پی\s*یو|प्रोसेसर"),
        ("gpu", r"\bgpu\b|graphics?|گرافکس|گرافک|جی\s*پی\s*یو|ग्राफिक्स"),
        ("storage", r"storage|\bdisk\b|\bdrives?\b|hard ?disk|\bspace\b|اسٹوریج|سٹوریج|سٹورج|ڈسک|स्टोरेज"),
        ("windows", r"\bwindows\b|ونڈوز|وندوز|ونڈو|विंडोज"),
        ("devices", r"\bmic\b|microphone|speakers?|camera|webcam|مائیک|مائک|کیمرہ|کیمرا|سپیکر|स्पीकर|कैमरा"),
        ("displays", r"monitors?|displays?|screens?|مانیٹر|ڈسپلے"),
        ("network", r"network|internet|wi-?fi|انٹرنیٹ|نیٹ\s*ورک|وائی\s*فائی|इंटरनेट"),
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

_DO = r"(?:karo|kar do|kardo|kar dein|kijiye|karein|kro|kar lo)"

# ---- computer control (Phase 6) ------------------------------------------------------------
TYPE_TEXT = [
    re.compile(r"^(?:(?:ye|yeh|is)\s+)?(?:type|likho|likh do|type karo)\s*[:\-]\s*(?P<text>.+)$", re.IGNORECASE),
    re.compile(r"^(?:please\s+)?type\s+(?P<text>.+)$", re.IGNORECASE),
    re.compile(r"^(?P<text>.+?)\s+(?:type karo|type kar do|likh do|likho)$", re.IGNORECASE),
]

SCREENSHOT = re.compile(r"\bscreen\s*shot\b|سکرین\s*شاٹ|اسکرین\s*شاٹ|स्क्रीनशॉट", re.IGNORECASE)

READ_SCREEN = [
    re.compile(r"^(?P<app>.+?)\s+(?:window\s+)?(?:mein|me|par|pe)\s+kya\s+(?:likha|likhaa)\b", re.IGNORECASE),
    re.compile(r"\bscreen\s+(?:par|pe|per|mein)\s+kya\b|\b(?:screen|window)\s+(?:read|parh|parho|padho|parhein)\b"
               r"|\bread\s+(?:my\s+|the\s+|this\s+)?(?:screen|window)\b|\bwhat'?s\s+on\s+(?:my\s+|the\s+)?screen\b"
               r"|سکرین\s+پر\s+کیا|اسکرین\s+پر\s+کیا|स्क्रीन\s+पर\s+क्या", re.IGNORECASE),
]

SHORTCUT_WORDS = {
    "copy": "copy", "paste": "paste", "cut": "cut", "undo": "undo", "redo": "redo", "select all": "select_all",
    "sab select": "select_all", "save": "save", "new tab": "new_tab", "naya tab": "new_tab", "tab band": "close_tab",
    "refresh": "refresh", "reload": "refresh", "enter": "enter", "escape": "escape",
}
KEYBOARD_SHORTCUT = re.compile(
    r"^(?:(?:ye|yeh|isko|is ko|sab kuch|text)\s+)?(?P<k>copy|paste|cut|undo|redo|select all|sab select|save|new tab|"
    r"naya tab|tab band|refresh|reload|enter|escape)\s*(?:" + _DO[3:-1] + r"|dabao|press karo|kholo)?$",
    re.IGNORECASE,
)

MOUSE_CLICK = [
    re.compile(r"^(?P<target>.+?)\s+(?:button\s+)?(?:par|pe|per)\s+click\s*(?:" + _DO[3:-1] + r")?$", re.IGNORECASE),
    re.compile(r"^(?:please\s+)?click\s+(?:on\s+)?(?:the\s+)?(?P<target>.+?)(?:\s+button)?$", re.IGNORECASE),
]

SHOW_DESKTOP = re.compile(
    r"\b(?:sab|saari|sari|all)\s+windows?\s+(?:minimi[sz]e|chhot[ie])|\bshow\s+(?:the\s+)?desktop\b|\bdesktop\s+dikhao\b",
    re.IGNORECASE,
)
WINDOW_CONTROL = [
    re.compile(r"^(?P<action>minimi[sz]e|maximi[sz]e|restore)\s+(?P<app>.+)$", re.IGNORECASE),
    re.compile(r"^(?:(?P<app>.+?)\s+(?:ko\s+|ki\s+window\s+)?)?(?:window\s+)?(?P<action>minimi[sz]e|maximi[sz]e|restore|"
               r"chhota|chhoti|chota|choti|bara|bari|bada|badi|full\s*screen)\s*" + _DO + r"?$", re.IGNORECASE),
]
WINDOW_ACTIONS = {"chhota": "minimize", "chhoti": "minimize", "chota": "minimize", "choti": "minimize",
                  "bara": "maximize", "bari": "maximize", "bada": "maximize", "badi": "maximize"}

CLOSE_APP = [
    re.compile(r"^(?:please\s+)?close\s+(?P<app>.+)$", re.IGNORECASE),
    re.compile(r"^(?P<app>.+?)\s+(?:ko\s+)?(?:band|close)\s+" + _DO + r"$", re.IGNORECASE),
    re.compile(r"^(?P<app>.+?)\s+(?:کو\s+)?بند\s+(?:کرو|کر دو|کریں)$"),
    re.compile(r"^(?P<app>.+?)\s+(?:को\s+)?बंद\s+(?:करो|कर दो)$"),
]

FOCUS_APP = [
    re.compile(r"^(?:switch\s+to|go\s+to|focus)\s+(?P<app>.+)$", re.IGNORECASE),
    re.compile(r"^(?P<app>.+?)\s+(?:pe|par|per)\s+(?:jao|chalo|le chalo|switch\s+" + _DO[3:-1] + r")$", re.IGNORECASE),
    re.compile(r"^(?P<app>.+?)\s+(?:ko\s+)?(?:samne|saamne|aage)\s+(?:lao|le aao|kar do|karo)$", re.IGNORECASE),
    re.compile(r"^(?P<app>.+?)\s+(?:پر\s+جاؤ|سامنے\s+لاؤ)$"),
]


# ---- browser + research (Phase 8A) ---------------------------------------------------------
_TLDS = (r"com|org|net|pk|io|dev|edu|gov|in|co|ai|app|tv|me|info|biz|uk|us|ca|au|de|fr|jp|xyz|site|online|tech|"
         r"blog|news|store|shop|ly|gg|so|to")
_URL = rf"(?P<url>(?:https?://)?(?:localhost(?::\d+)?|(?:[a-z0-9-]+\.)+(?:{_TLDS})(?::\d+)?)(?:/\S*)?)"
OPEN_WEBSITE = [
    re.compile(rf"^(?:please\s+)?(?:open|kholo|go\s+to|visit)\s+(?:website\s+|site\s+)?{_URL}$", re.IGNORECASE),
    re.compile(rf"^{_URL}\s+(?:website\s+|site\s+)?(?:kholo|khol do|open\s+{_DO}|(?:par|pe)\s+jao|chalao|visit\s+{_DO})$",
               re.IGNORECASE),
    re.compile(r"^(?P<url>.+?)\s+(?:website|site)\s+(?:kholo|khol do|open\s+" + _DO[3:-1] + r"|(?:par|pe)\s+jao)$",
               re.IGNORECASE),
]

RESEARCH = [
    re.compile(r"^(?P<q>.+?)\s+(?:ke|ki|ka)\s+(?:baare|bare|mutalliq)\s+(?:mein|me)\s+(?:research|tehqeeq|report)\s*"
               r"(?:karo|kar do|kijiye|banao|bana do|likho)?$", re.IGNORECASE),
    re.compile(r"^(?P<q>.+?)\s+(?:par|pe)\s+(?:research|tehqeeq|report)\s*(?:karo|kar do|kijiye|banao|bana do|likho)?$",
               re.IGNORECASE),
    re.compile(r"^(?P<q>.+?)\s+(?:ki|ka)\s+(?:report|research)\s+(?:banao|bana do|likho|karo)$", re.IGNORECASE),
    re.compile(r"^(?:research|do\s+research\s+on|research\s+about|make\s+a\s+report\s+on|write\s+a\s+report\s+on)\s+"
               r"(?P<q>.+)$", re.IGNORECASE),
    re.compile(r"^(?P<q>.+?\s+(?:aur|and|vs\.?|versus)\s+.+?)\s+(?:ka|ki|mein)\s+(?:comparison|muqabla|muqabila)\s*"
               r"(?:karo|kar do|batao)?$", re.IGNORECASE),
    re.compile(r"^compare\s+(?P<q>.+)$", re.IGNORECASE),
]

# Questions that need live information: answered from the web with sources.
ENGINE_LOOKUP = [
    re.compile(r"^(?:google|bing|duckduckgo)\s+(?:pe|par|mein|me)\s+(?:dekho|dekh\s+lo|check\s+karo|dhoondo)\s+(?P<query>.+)$",
               re.IGNORECASE),
    re.compile(r"^(?P<query>.+?)\s+(?:google|bing|duckduckgo)\s+(?:pe|par|mein|me)\s+(?:dekho|dekh\s+lo|check\s+karo|dhoondo)$",
               re.IGNORECASE),
]

SEARCH_REQUEST = re.compile(r"\bsearch\s+(?:karo|kar do|kardo|kijiye|karein)$", re.IGNORECASE)

WEB_ANSWER = re.compile(
    r"\b(?:mausam|weather|temperature|darja\s+hararat)\b"
    r"|\b(?:latest|taaza|taza|aaj\s+ki|aaj\s+ka|abhi\s+ki)\s+(?:news|khabar|khabrein|khabren|update|updates|score)\b"
    r"|\b(?:dollar|gold|sona|petrol|bitcoin)\s+(?:ka|ki)\s+(?:rate|qeemat|keemat|price)\b"
    r"|موسم|मौसम",
    re.IGNORECASE,
)

READ_PAGE = re.compile(
    r"\b(?:is|ye|yeh|this|current)\s+(?:page|website|article|site|webpage)\s+(?:ko\s+)?(?:parho|parh\s+do|read\s+karo|"
    r"summari[sz]e\s*(?:karo|kar\s+do)?|ka\s+khulasa\s*(?:batao|do|karo)?|mein\s+kya\s+(?:hai|likha\s+hai))"
    r"|\bsummari[sz]e\s+(?:this\s+|the\s+)?(?:page|website|article)\b|\bpage\s+(?:ka\s+)?(?:khulasa|summary)\b"
    r"|\bread\s+(?:this|the)\s+(?:page|article)\b",
    re.IGNORECASE,
)

SCROLL = re.compile(r"\bscroll\s+(?P<d>down|up|neeche|niche|upar)\b|\b(?P<d2>neeche|niche|upar|down|up)\s+scroll\b",
                    re.IGNORECASE)
BROWSER_BACK = re.compile(r"^(?:browser\s+mein\s+)?(?:go\s+back|back\s+(?:jao|karo|chalo)|peeche\s+(?:jao|chalo)|"
                          r"pichle\s+page\s+(?:par|pe)\s+(?:jao|chalo))$", re.IGNORECASE)
BROWSER_FORWARD = re.compile(r"^(?:browser\s+mein\s+)?(?:go\s+forward|forward\s+(?:jao|karo)|aage\s+(?:jao|chalo)|"
                             r"agle\s+page\s+(?:par|pe)\s+(?:jao|chalo))$", re.IGNORECASE)
BROWSER_RELOAD = re.compile(r"^(?:page\s+)?reload\s*(?:karo|kar do)?$", re.IGNORECASE)

BROWSER_CLICK = [
    re.compile(r"^(?P<target>.+?)\s+link\s+(?:par|pe)\s+click\s*(?:karo|kar do|kijiye)?$", re.IGNORECASE),
    re.compile(r"^click\s+(?:on\s+)?(?:the\s+)?(?P<target>.+?)\s+link$", re.IGNORECASE),
]
BROWSER_TYPE = re.compile(
    r"^(?P<field>.+?\s+(?:box|field|khane|khana|bar))\s+(?:mein|me)\s+(?P<text>.+?)\s+"
    r"(?:likho|likh do|type karo|bharo|bhar do|daalo|dalo)$", re.IGNORECASE)
DOWNLOAD = [
    re.compile(r"^(?P<target>.+?)\s+(?:download|dawnload)\s*(?:karo|kar do|kar lo|kijiye)?$", re.IGNORECASE),
    re.compile(r"^download\s+(?P<target>.+)$", re.IGNORECASE),
]


def _browser_intent(cleaned: str) -> tuple[str, dict[str, object]] | None:
    for p in RESEARCH:
        if m := p.search(cleaned):
            return "research", {"query": m.group("q").strip(" ?.")}
    # A named search engine or "... search karo" asks for a browser search, even about the weather or a rate.
    for p in ENGINE_LOOKUP:
        if m := p.search(cleaned):
            return "web_search", {"query": m.group("query").strip(" ?.")}
    if SEARCH_REQUEST.search(cleaned):
        return None  # handled by WEB_SEARCH
    if WEB_ANSWER.search(cleaned):
        return "web_answer", {"query": cleaned}
    if READ_PAGE.search(cleaned):
        return "read_page", {}
    if m := SCROLL.search(cleaned):
        d = (m.group("d") or m.group("d2")).lower()
        return "browser_nav", {"action": "scroll_down" if d in ("down", "neeche", "niche") else "scroll_up"}
    if BROWSER_BACK.search(cleaned):
        return "browser_nav", {"action": "back"}
    if BROWSER_FORWARD.search(cleaned):
        return "browser_nav", {"action": "forward"}
    if BROWSER_RELOAD.search(cleaned):
        return "browser_nav", {"action": "reload"}
    if m := BROWSER_TYPE.search(cleaned):
        return "browser_type", {"field": m.group("field").strip(), "text": m.group("text").strip()}
    for p in BROWSER_CLICK:
        if m := p.search(cleaned):
            return "browser_click", {"target": _clean_entity(m.group("target"))}
    for p in DOWNLOAD:
        if m := p.search(cleaned):
            return "download", {"target": _clean_entity(m.group("target"))}
    for p in OPEN_WEBSITE:
        if m := p.search(cleaned):
            return "open_website", {"url": m.group("url").strip()}
    return None


def _computer_intent(cleaned: str) -> tuple[str, dict[str, object]] | None:
    """Action commands. Explicit dictation ("likho: ...") is checked first so dictated text is never treated as
    a command; browser commands come before the ambiguous trailing "... likho" form."""
    for p in TYPE_TEXT[:2]:
        if m := p.search(cleaned):
            return "type_text", {"text": m.group("text").strip()}
    if browser := _browser_intent(cleaned):
        return browser
    for p in TYPE_TEXT[2:]:
        if m := p.search(cleaned):
            return "type_text", {"text": m.group("text").strip()}
    if SCREENSHOT.search(cleaned):
        return "screenshot", {}
    for p in READ_SCREEN:
        if m := p.search(cleaned):
            app = _clean_entity(m.groupdict().get("app"))
            return "read_screen", {"app": app} if app and app.lower() not in ("screen", "is", "ye") else {}
    if m := KEYBOARD_SHORTCUT.search(cleaned):
        return "keyboard_shortcut", {"keys": SHORTCUT_WORDS[m.group("k").lower()]}
    if SHOW_DESKTOP.search(cleaned):
        return "window_control", {"action": "show_desktop"}
    for p in WINDOW_CONTROL:
        if m := p.search(cleaned):
            raw = m.group("action").lower().replace(" ", "")
            action = WINDOW_ACTIONS.get(raw, "maximize" if raw == "fullscreen" else raw.replace("mise", "mize"))
            app = _clean_entity(m.group("app"))
            return "window_control", {"action": action, **({"app": app} if app else {})}
    for p in CLOSE_APP:
        if m := p.search(cleaned):
            return "close_app", {"app": _clean_entity(m.group("app"))}
    for p in FOCUS_APP:
        if m := p.search(cleaned):
            return "focus_app", {"app": _clean_entity(m.group("app"))}
    for p in MOUSE_CLICK:
        if m := p.search(cleaned):
            return "mouse_click", {"target": _clean_entity(m.group("target"))}
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

COMPOUND_SPLIT = re.compile(r"\s*(?:,\s*)?\b(?:aur phir|aur|and then|and|phir|then)\b\s*|\s+(?:اور|پھر|और|फिर)\s+", re.IGNORECASE)

FOLDER_DETERMINERS ={"ye", "yeh", "is", "ek", "aik", "naya", "new", "this", "a"}

TRAILING_PUNCT =re.compile(r"[\s.!?۔،,]+$")


def normalize(text: str, wake: re.Pattern[str] = WAKE_WORD) -> str:
    text = wake.sub("", text.strip())
    return TRAILING_PUNCT.sub("", text).strip()


FILLER_PREFIX = re.compile(
    r"^(?:(?:the|a|an|first|please|plz|zara|jaldi|jaldi se|bhai|yaar|yar|pehle|pahle|mera|meri|mere|my|ye|yeh|is|wo|woh)\s+)+",
    re.IGNORECASE,
)


PRONOUNS = {"isko", "isey", "ise", "usko", "usey", "use", "ye", "yeh", "wo", "woh", "it", "this", "that", "inko",
             "unko", "اسے", "اس کو", "इसे", "इसको", "उसे"}

FILLER_SUFFIX = re.compile(
    r"(?:\s+(?:for me|please|plz|mere liye|mera|jaldi|zara|now|abhi))+$"
    # "WhatsApp wali window", "Chrome app", "Notepad ki window" -> the app name only
    r"|(?:\s+(?:wali|wala|wale|ki|ka))?\s+(?:window|app|application)$",
    re.IGNORECASE,
)
# "desktop par Projects" -> "Projects": a location phrase in front of a name is not part of the name.
LOCATION_PREFIX = re.compile(
    r"^(?:(?:desktop|documents|downloads|pictures|music|videos|[a-z]:\\?|d drive|c drive)\s+(?:par|pe|mein|me|main|on|in)\s+)",
    re.IGNORECASE,
)


def _clean_entity(value: str | None) -> str | None:
    if not value:
        return None
    value = FILLER_PREFIX.sub("", value.strip())
    value = LOCATION_PREFIX.sub("", value)
    value = FILLER_SUFFIX.sub("", value)
    return value.strip(" \"'") or None


class RuleBasedProvider(AIProvider):
    name = "rule_based"
    is_local = True

    def __init__(self) -> None:
        self._wake = WAKE_WORD

    def configure_wake(self, assistant_name: str, wake_word: str) -> None:
        self._wake = build_wake_pattern(assistant_name, wake_word)

    async def understand(self, text: str, context: list[ConversationTurn] | None = None) -> Understanding:
        """Splits compound commands ("Chrome kholo aur RAM batao") when every part is understood."""
        cleaned = normalize(text, self._wake)
        # Explicit dictation ("likho: main aur tum", "type hello and bye") is never split into commands.
        # The trailing form ("... type karo") is ambiguous, so it may still be one part of a compound.
        dictation = any(p.search(cleaned) for p in TYPE_TEXT[:2])
        parts = [] if dictation else [p for p in COMPOUND_SPLIT.split(cleaned) if p.strip()]
        if len(parts) > 1:
            intents = [await self.detect_intent(p) for p in parts]
            if all(i.name not in ("unknown", "greeting") for i in intents):
                language = detect_language(text)
                unique: list[Intent] = []
                for i in intents:
                    i.language = language
                    if not any(u.name == i.name and u.entities == i.entities for u in unique):
                        unique.append(i)  # "mic aur camera" -> one devices query, not two
                return Understanding(intents=unique, provider=self.name)
        return Understanding(intents=[await self.detect_intent(text)], provider=self.name)

    async def detect_intent(self, text: str) -> Intent:
        language = detect_language(text)
        cleaned = normalize(text, self._wake)
        # Rules are precise on short commands; long conversational sentences are less certain,
        # which lets hybrid mode hand them to the LLM.
        damping = 0.75 if len(cleaned.split()) > 8 else 1.0

        def make(name: str, confidence: float, **entities: object) -> Intent:
            return Intent(
                name=name,
                confidence=round(confidence * damping, 3),
                language=language,
                entities={k: v for k, v in entities.items() if v is not None},
                provider=self.name,
            )

        if not cleaned:
            return make("greeting", 0.9)  # bare wake word

        if m := RUN_WORKFLOW.search(cleaned):
            return make("run_workflow", 0.8, workflow=(m.group("name") or m.group("name2")).lower())

        if computer := _computer_intent(cleaned):
            name, entities = computer
            app = entities.get("app")
            # "isko band karo" needs context, except words that mean "the current window".
            vague = isinstance(app, str) and app.lower() in PRONOUNS and name not in ("window_control", "read_screen")
            return make(name, 0.3 if vague else 0.85, **entities)

        for pattern in CREATE_FOLDER:
            if m := pattern.search(cleaned):
                name = _clean_entity(m.groupdict().get("name"))
                if name and name.lower() in FOLDER_DETERMINERS:
                    name = None
                return make("create_folder", 0.8, folder_name=name)

        for pattern in WEB_SEARCH:
            if m := pattern.search(cleaned):
                query = _clean_entity(m.groupdict().get("query"))
                if query:  # "dollar rate google par search karo": the engine is a place, not part of the query
                    query = re.sub(r"\s+(?:google|bing|duckduckgo|internet|web)\s+(?:par|pe|mein|me)$", "", query,
                                   flags=re.IGNORECASE) or query
                return make("web_search", 0.8, query=query)

        for pattern in OPEN_APP:
            if m := pattern.search(cleaned):
                app = _clean_entity(m.group("app"))
                # "isko kholo" refers to something said earlier: only the LLM (with context) can resolve it.
                return make("open_app", 0.3 if app and app.lower() in PRONOUNS else 0.85, app=app)

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
