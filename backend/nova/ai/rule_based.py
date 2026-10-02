"""Deterministic intent parser for Urdu, Roman Urdu, Hindi and English.

This is the offline fallback provider. An LLM provider (Ollama) will replace it as the
primary brain in Phase 4, but this one stays available when no model is installed.
"""

from __future__ import annotations

import re

from ..language import detect_language
from ..memory.facts import detect_fact
from .base import AIProvider, ConversationTurn, Intent, Understanding

BUILTIN_NAMES = ("nova", "نووا", "नोवा")


def build_wake_pattern(assistant_name: str = "NOVA", wake_word: str = "Hey NOVA") -> re.Pattern[str]:
    """Matches the configured wake word, or '[hey] <name>', at the start of an utterance."""
    names = "|".join(sorted({re.escape(assistant_name), *BUILTIN_NAMES}, key=len, reverse=True))
    # A bare name followed by "project"/"ka"/"mein"... is part of the command ("nova project kholo" means the
    # project called nova), not a wake word. With "hey" in front it always is the wake word.
    part_of_command = r"(?!\s+(?:project|projects|folder|ka|ki|ke|mein|me|wala|wali|wale)\b)"
    # "(?!-?\w)": a name joined to the next word ("NOVA-Test-8B", "nova-demo") is a name, not a wake word.
    return re.compile(
        rf"^\s*(?:{re.escape(wake_word)}|(?:hey|hi|ok|ay|ae|اے|ہے)\s*(?:{names})|(?:{names}){part_of_command})"
        rf"(?!-?\w)[\s,!.:-]*",
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


# ---- files + coding (Phase 8B) -------------------------------------------------------------
_WEB_TLDS = frozenset(_TLDS.split("|"))
_FILENAME = r"[^\s\"'“‘][^\"”’]*?\.[A-Za-z0-9]{1,8}"  # "notes.txt", "final report.docx"
_Q = r"[\"'“”‘’]?"
_PRON = r"(?:is|us|ye|yeh|wo|woh)\s+(?:file|folder)|isko|isey|ise|isay|usko|usay|usey"
_CODE_EXT = "py|js|mjs|cjs|ts|tsx|jsx|php|html|htm|css|scss|vue|java|kt|c|h|cpp|cs|go|rs|rb|dart|sql"
_FOLDER_WORDS = re.compile(r"^(?:desktop|documents?|docs|downloads?|pictures?|photos|tasveerein|music|videos?|htdocs)$",
                           re.IGNORECASE)
_FILE_WORD = re.compile(r"\b(?:file|files|folder|folders)\b", re.IGNORECASE)
_ORDINAL_TARGET = re.compile(r"^(?:pehli|pehla|pehle|doosri|dusri|doosra|teesri|teesra|chauthi|first|second|third|"
                             r"(?:number\s+)?\d+)(?:\s+(?:number|wali|wala|file|folder))*$", re.IGNORECASE)

UNDO_FILE = [
    re.compile(r"^(?:pichla|pichhla|aakhri|akhri|last)\s+(?:file\s+(?:wala\s+)?)?(?:kaam|operation|change|tabdeeli)\s+"
               r"(?:wapas|undo|ulta)\s*(?:karo|kar do|lo|le lo)?$", re.IGNORECASE),
    re.compile(r"^(?:file|files|rename|move|organi[sz]e|edit|tabdeeli)\s+(?:wala\s+kaam\s+)?(?:wapas|undo)\s+(?:karo|kar do)$",
               re.IGNORECASE),
    re.compile(r"^undo\s+(?:the\s+|my\s+)?last\s+(?:file\s+)?(?:change|operation|action)$", re.IGNORECASE),
]
SEARCH_FILES = [
    re.compile(r"^(?:(?P<loc>.+?)\s+(?:mein|me|par|pe)\s+)?(?P<q>.+?)\s+(?:naam\s+(?:ki|ka|ke)\s+|wali\s+|wala\s+|wale\s+|"
               r"ki\s+(?:saari\s+|sab\s+)?|ke\s+)?"
               r"(?P<kind>files?|folders?)\s+(?:dhoondo|dhundo|dhoond do|dhund do|talash karo|search karo|search kar do|"
               r"find karo|dikhao|batao)$", re.IGNORECASE),
    re.compile(r"^(?:find|search(?:\s+for)?|show(?:\s+me)?)\s+(?:all\s+|my\s+)?(?P<q>.+?)\s+(?P<kind>files?|folders?)"
               r"(?:\s+in\s+(?P<loc>.+))?$", re.IGNORECASE),
    re.compile(r"^(?:find|search(?:\s+for)?)\s+(?:the\s+)?(?P<kind>files?|folders?)\s+(?:named\s+|called\s+)?(?P<q>.+?)"
               r"(?:\s+in\s+(?P<loc>.+))?$", re.IGNORECASE),
    re.compile(rf"^(?P<q>{_FILENAME})\s+(?:kahan|kidhar)\s+(?:hai|he|pari hai|para hai|rakhi hai)$", re.IGNORECASE),
]
CREATE_FILE_WITH_TEXT = re.compile(
    rf"^(?:(?P<loc>.+?)\s+(?:mein|me|par|pe)\s+)?(?P<name>{_FILENAME})\s+(?:naam\s+(?:ki|ka)\s+)?(?:nayi\s+|new\s+)?"
    rf"(?:file\s+)?(?:banao|bana do|create karo|create kar do)\s+(?:aur|jis)\s+(?:us\s+|is\s+)?(?:mein|me)\s+"
    rf"{_Q}(?P<text>.+?){_Q}\s+(?:likho|likh do|daalo|daal do)$", re.IGNORECASE)
CREATE_FILE = [
    re.compile(rf"^(?:(?P<loc>.+?)\s+(?:mein|me|par|pe)\s+)?(?P<name>{_FILENAME})\s+(?:naam\s+(?:ki|ka)\s+)?(?:nayi\s+|new\s+)?"
               r"(?:file\s+)?(?:banao|bana do|create karo|create kar do)$", re.IGNORECASE),
    re.compile(r"^(?:(?P<loc>.+?)\s+(?:mein|me|par|pe)\s+)?(?P<name>.+?)\s+naam\s+(?:ki|ka)\s+(?:nayi\s+|new\s+)?file\s+"
               r"(?:banao|bana do|create karo|create kar do)$", re.IGNORECASE),
    re.compile(r"^(?:create|make)\s+(?:a\s+)?(?:new\s+)?(?:text\s+)?file\s+(?:named\s+|called\s+)?(?P<name>.+?)"
               r"(?:\s+(?:in|on)\s+(?P<loc>.+))?$", re.IGNORECASE),
]
CREATE_FOLDER_AT = [
    re.compile(r"^(?:(?P<loc>.+?)\s+(?:mein|me|par|pe)\s+)?(?P<name>.+?)\s+(?:naam\s+(?:ka|ki)\s+)?(?:naya\s+|new\s+)?"
               r"folder\s+(?:banao|bana do|create karo|create kar do)$", re.IGNORECASE),
    re.compile(r"^(?:create|make)\s+(?:a\s+)?(?:new\s+)?folder\s+(?:named\s+|called\s+)?(?P<name>.+?)"
               r"(?:\s+(?:in|on)\s+(?P<loc>.+))?$", re.IGNORECASE),
]
OPEN_FILE = [
    re.compile(rf"^(?P<target>{_FILENAME})\s+(?:file\s+)?(?:kholo|khol do|open karo|open kar do|chalao|chala do)$",
               re.IGNORECASE),
    re.compile(rf"^(?P<target>.+?\s+folder|{_PRON})\s+(?:ko\s+)?(?:kholo|khol do|open karo|open kar do)$", re.IGNORECASE),
    re.compile(rf"^open\s+(?:the\s+)?(?:file\s+)?(?P<target>{_FILENAME})$", re.IGNORECASE),
    re.compile(r"^open\s+(?:the\s+|my\s+)?(?P<target>.+?\s+folder)$", re.IGNORECASE),
]
READ_FILE_SUMMARY = [
    re.compile(rf"^(?P<target>{_FILENAME}|{_PRON})\s+(?:ka|ki)\s+(?:khulasa|khulaasa|summary)\s*"
               r"(?:batao|do|karo|dikhao|bata do|sunao)?$", re.IGNORECASE),
    re.compile(rf"^(?P<target>{_FILENAME}|{_PRON})\s+(?:ko\s+)?summari[sz]e\s*(?:karo|kar do)?$", re.IGNORECASE),
    re.compile(rf"^summari[sz]e\s+(?:the\s+)?(?:file\s+)?(?P<target>{_FILENAME})$", re.IGNORECASE),
]
READ_FILE = [
    re.compile(rf"^(?P<target>{_FILENAME}|{_PRON}|.+?\s+file)\s+(?:ko\s+)?(?:parho|padho|parh do|parh kar sunao|read karo|"
               r"dikhao|ka content dikhao|mein kya (?:likha )?hai)$", re.IGNORECASE),
    re.compile(r"^(?P<target>.+?)\s+(?:mein|me)\s+(?:kya\s+kya|kya)\s+(?:hai|hain|para hai|pada hai)$", re.IGNORECASE),
    re.compile(r"^(?P<target>.+?)\s+(?:ki|ke)\s+(?:saari\s+|sab\s+)?(?:files|cheezein)\s+(?:dikhao|batao)$", re.IGNORECASE),
    re.compile(rf"^(?:read|show)\s+(?:me\s+)?(?:the\s+)?(?:file\s+)?(?P<target>{_FILENAME})$", re.IGNORECASE),
]
RENAME_FILE = [
    re.compile(r"^(?P<target>.+?)\s+(?:ka|ki)\s+naam\s+(?:badal\s+kar\s+)?(?P<new>.+?)\s+(?:rakh do|rakho|rakh dein|kar do|karo)$",
               re.IGNORECASE),
    re.compile(r"^(?P<target>.+?)\s+ko\s+(?P<new>.+?)\s+(?:se|mein|me|naam se)\s+rename\s+(?:karo|kar do)$", re.IGNORECASE),
    re.compile(r"^(?P<target>.+?)\s+(?:ko\s+)?rename\s+(?:karo|kar do)\s*[:\-]?\s*(?P<new>.+)$", re.IGNORECASE),
    re.compile(r"^rename\s+(?P<target>.+?)\s+(?:to|as)\s+(?P<new>.+)$", re.IGNORECASE),
]
MOVE_FILE = [
    re.compile(r"^(?P<target>.+?)\s+ko\s+(?P<dest>.+?)\s+(?:mein|me|par|pe)\s+(?:move|shift)\s*(?:karo|kar do|kar dein)?$",
               re.IGNORECASE),
    re.compile(r"^(?P<target>.+?)\s+ko\s+(?P<dest>.+?)\s+(?:mein|me)\s+(?:le jao|rakh do|daal do|dal do|pohncha do)$",
               re.IGNORECASE),
    re.compile(r"^move\s+(?P<target>.+?)\s+(?:to|into)\s+(?P<dest>.+)$", re.IGNORECASE),
]
COPY_FILE = [
    re.compile(r"^(?P<target>.+?)\s+ko\s+(?P<dest>.+?)\s+(?:mein|me|par|pe)\s+copy\s*(?:karo|kar do|kar dein)$", re.IGNORECASE),
    re.compile(r"^(?P<target>.+?)\s+(?:ki|ka)\s+(?:copy|nakal)\s+(?:banao|bana do)$", re.IGNORECASE),
    re.compile(r"^copy\s+(?P<target>.+?)\s+(?:to|into)\s+(?P<dest>.+)$", re.IGNORECASE),
]
DELETE_FILE = [
    re.compile(r"^(?P<target>.+?)\s+(?:ko\s+)?(?:delete|mita|hata|remove|trash)\s*(?:karo|kar do|kardo|do|dein|kar dein|kijiye)$",
               re.IGNORECASE),
    re.compile(r"^(?:delete|remove|trash)\s+(?:the\s+)?(?P<target>.+)$", re.IGNORECASE),
]
EDIT_REPLACE = [
    re.compile(rf"^(?P<target>{_FILENAME}|{_PRON})\s+(?:mein|me)\s+{_Q}(?P<old>.+?){_Q}\s+ko\s+{_Q}(?P<new>.+?){_Q}\s+"
               r"(?:se|mein|me)\s+(?:badal do|badlo|badal dein|replace karo|replace kar do|change karo|change kar do)$",
               re.IGNORECASE),
    re.compile(rf"^(?:in\s+(?P<target>{_FILENAME})\s*,?\s+)?replace\s+{_Q}(?P<old>.+?){_Q}\s+with\s+{_Q}(?P<new>.+?){_Q}"
               rf"(?:\s+in\s+(?P<target2>{_FILENAME}))?$", re.IGNORECASE),
]
EDIT_APPEND = [
    re.compile(rf"^(?P<target>{_FILENAME}|{_PRON})\s+(?:mein|me)\s+(?:ye\s+|yeh\s+)?(?:likho|likh do|add karo|add kar do|"
               r"jor do|daal do)\s*[:\-]\s*(?P<text>.+)$", re.IGNORECASE),
    re.compile(rf"^(?P<target>{_FILENAME}|{_PRON})\s+(?:mein|me)\s+(?P<text>.+?)\s+(?:likho|likh do|add karo|add kar do|"
               r"jor do|daal do)$", re.IGNORECASE),
    re.compile(rf"^(?:add|append|write)\s+{_Q}(?P<text>.+?){_Q}\s+(?:to|in|into)\s+(?P<target>{_FILENAME})$", re.IGNORECASE),
]
ORGANIZE_FOLDER = [
    re.compile(r"^(?P<loc>.+?)\s+(?:ko\s+)?(?:organi[sz]e|arrange)\s*(?:karo|kar do|kar dein|kijiye)?$", re.IGNORECASE),
    re.compile(r"^(?P<loc>.+?)\s+(?:ki|ko)\s+(?:files\s+(?:ko\s+)?)?(?:tarteeb|tartib)\s+(?:do|de do|dein|se rakho|"
               r"se laga do)$", re.IGNORECASE),
    re.compile(r"^(?:organi[sz]e|arrange|tidy\s+up|clean\s+up)\s+(?:my\s+|the\s+)?(?P<loc>.+?)$", re.IGNORECASE),
]
FOLDER_REPORT = [
    re.compile(r"^(?P<loc>.+?)\s+(?:ki|ka)\s+(?:report|jaiza)\s+(?:banao|bana do|do|dikhao|batao|tayyar karo)$", re.IGNORECASE),
    re.compile(r"^(?:make|create|give\s+me)\s+(?:a\s+)?report\s+(?:of|on|for|about)\s+(?:my\s+|the\s+)?(?P<loc>.+?)$",
               re.IGNORECASE),
]
MODIFY_CODE = [
    re.compile(rf"^(?:(?P<p>.+?)\s+project\s+(?:ki|ke|ka|mein|me)\s+)?(?P<target>[^\s\"']+?\.(?:{_CODE_EXT}))\s+(?:mein|me)\s+"
               r"(?P<instr>.+?\s+(?:karo|kar do|kar dein|kijiye|badlo|badal do|hatao|hata do|likho|likh do|banao|bana do|"
               r"lagao|laga do|jor do|daalo|daal do))$", re.IGNORECASE),
    re.compile(rf"^in\s+(?P<target>[^\s\"']+?\.(?:{_CODE_EXT}))\s*,?\s+(?P<instr>(?:add|remove|change|rename|replace|fix|"
               r"make|use|update|delete)\b.+)$", re.IGNORECASE),
]

OPEN_PROJECT = [
    re.compile(r"^(?P<p>.+?)\s+project\s+(?:ko\s+)?(?:vs\s*code|code)\s+(?:mein|me)\s+(?:kholo|khol do|open karo|open kar do)$",
               re.IGNORECASE),
    re.compile(r"^(?:vs\s*code|code)\s+(?:mein|me)\s+(?P<p>.+?)(?:\s+project|\s+folder)?\s+(?:kholo|khol do|open karo|"
               r"open kar do)$", re.IGNORECASE),
    re.compile(r"^(?P<p>.+?)\s+project\s+(?:kholo|khol do|open karo|open kar do)$", re.IGNORECASE),
    re.compile(r"^open\s+(?:the\s+|my\s+)?(?P<p>.+?)\s+project(?:\s+in\s+(?:vs\s*)?code)?$", re.IGNORECASE),
]
LIST_PROJECTS = re.compile(
    r"^(?:mere\s+|meri\s+|sab\s+|saare\s+|all\s+|my\s+)?projects?\s+(?:ki\s+list\s+)?(?:dikhao|batao|list karo)$"
    r"|^(?:kaun|kon)\s*(?:se|si)\s+projects?\s+(?:hain|hai)$|^(?:list|show)\s+(?:me\s+)?(?:my\s+|all\s+)?projects$",
    re.IGNORECASE)
INSPECT_PROJECT = [
    re.compile(r"^(?P<p>.+?)\s+project\s+(?:ka|ki|ke)\s+(?:jaiza|jaeza|review|structure|tafseel|maloomat|details?|overview)"
               r"\s*(?:lo|le lo|do|dikhao|batao|karo|bataen)?$", re.IGNORECASE),
    re.compile(r"^(?P<p>.+?)\s+project\s+(?:ke\s+baare\s+mein\s+batao|mein\s+kya\s+(?:hai|hain)|check\s+karo|inspect\s+karo|"
               r"samjhao|dekho)$", re.IGNORECASE),
    re.compile(r"^(?:inspect|analy[sz]e|review|describe)\s+(?:the\s+|my\s+)?(?P<p>.+?)\s+project$", re.IGNORECASE),
]
RUN_TESTS = [
    re.compile(r"^(?:(?P<p>.+?)\s+(?:project\s+)?(?:ke|ki|ka|mein|me)\s+)?(?:saare\s+|sab\s+)?tests?\s+(?:chalao|chala do|"
               r"run karo|run kar do|chalaiye|chala kar dekho)$", re.IGNORECASE),
    re.compile(r"^run\s+(?:the\s+|all\s+)?tests?(?:\s+(?:for|in|of)\s+(?:the\s+)?(?P<p>.+?)(?:\s+project)?)?$", re.IGNORECASE),
]
CHECK_ERRORS = [
    re.compile(r"^(?:(?P<p>.+?)\s+(?:project\s+)?(?:mein|me|ke|ki|ka)\s+)?(?:code\s+(?:ke|ki|mein)\s+)?(?:errors?|ghaltiyan|"
               r"ghaltiyaan|ghalatiyan|bugs?|masle)\s+(?:check\s+karo|check\s+kar\s+do|dhoondo|dhundo|dekho|batao|chek\s+karo)$",
               re.IGNORECASE),
    re.compile(r"^(?:check|find)\s+(?:the\s+|for\s+)?(?:errors|bugs)(?:\s+in\s+(?:the\s+)?(?P<p>.+?)(?:\s+project)?)?$",
               re.IGNORECASE),
]
RUN_COMMAND = [
    re.compile(r"^(?:(?P<p>.+?)\s+(?:project\s+)?(?:mein|me|ka|ki|ke)\s+)?(?P<cmd>npm\s+(?:run\s+)?[\w:.\-]+|git\s+(?:status|diff|log)|"
               r"build|lint|typecheck|dev\s+server|server|dependencies(?:\s+install)?|packages(?:\s+install)?)\s+"
               r"(?:chalao|chala do|run karo|run kar do|start karo|start kar do|install karo|install kar do)$", re.IGNORECASE),
    re.compile(r"^run\s+(?P<cmd>npm\s+(?:run\s+)?[\w:.\-]+|git\s+(?:status|diff|log))(?:\s+in\s+(?:the\s+)?(?P<p>.+?)"
               r"(?:\s+project)?)?$", re.IGNORECASE),
]
EXPLAIN_ERROR = [
    re.compile(r"^(?:(?:ye|yeh|is|wo|us|pichla|aakhri)\s+)?(?:error|errors|ghalti|masla)\s+(?:samjhao|samjha do|explain karo|"
               r"explain kar do|ka matlab batao|kya hai|kyun aaya|kyon aaya)\s*(?:[:\-]\s*(?P<text>.+))?$", re.IGNORECASE),
    re.compile(r"^explain\s+(?:this\s+|the\s+)?error(?:\s*[:\-]\s*(?P<text>.+))?$", re.IGNORECASE),
]
FIX_ERROR = [
    re.compile(r"^(?:(?:ye|yeh|is|wo|us|pichla|aakhri|sab|saare)\s+)?(?:error|errors|ghalti|ghaltiyan|masla|bug)\s+"
               r"(?:theek|thik|fix|durust|hal)\s+(?:karo|kar do|kijiye|kar dein)$", re.IGNORECASE),
    re.compile(r"^fix\s+(?:this\s+|the\s+)?(?:error|bug)s?$", re.IGNORECASE),
]
# ---- system settings, messages, design (Phase 8C) ------------------------------------------
_VOL = r"(?:volume|awaaz|aawaz|awaz|sound|speaker\s+ki\s+awaaz)"
_LEVEL_WORDS = re.compile(r"\d|kam|zyada|ziada|barha|ghata|tez|dheem|halk|full|poor|pura|aadh|half|max|min|\bup\b|"
                          r"\bdown\b|high|low|ooncha|oonchi", re.IGNORECASE)
_SET_END = r"\s*(?:kar do|karo|kardo|kijiye|kar dein|rakho|set karo|par kar do|par set karo|ho jaye)?"
SETTING_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("mute", re.compile(rf"^(?:{_VOL}\s+)?mute\s*(?:karo|kar do|kardo)?$|^{_VOL}\s+band\s*(?:karo|kar do|kardo)?$|"
                        r"^(?:computer|pc|laptop)\s+(?:ko\s+)?mute\s+(?:karo|kar do)$", re.IGNORECASE)),
    ("unmute", re.compile(rf"^(?:{_VOL}\s+)?unmute\s*(?:karo|kar do)?$|^{_VOL}\s+(?:wapas\s+)?(?:chalu|khol|on)\s*"
                          r"(?:karo|kar do)?$", re.IGNORECASE)),
    ("volume", re.compile(rf"^(?:{_VOL})\s+(?:ko\s+)?(?P<value>.+?){_SET_END}$", re.IGNORECASE)),
    ("volume", re.compile(r"^(?:turn|set)\s+(?:the\s+)?volume\s+(?:to\s+)?(?P<value>.+)$", re.IGNORECASE)),
    ("brightness", re.compile(rf"^(?:screen\s+ki\s+)?(?:brightness|roshni|chamak)\s+(?:ko\s+)?(?P<value>.+?){_SET_END}$",
                              re.IGNORECASE)),
    ("theme", re.compile(r"^(?P<value>(?:dark|light|kala)\s+(?:mode|theme)(?:\s+(?:on|off|chalu|band|lagao|laga do|"
                         r"enable|disable))?)\s*(?:karo|kar do|kardo)?$", re.IGNORECASE)),
    ("theme", re.compile(r"^(?:windows\s+(?:ko\s+)?)?(?:mode|theme)\s+(?P<value>dark|light)\s+(?:karo|kar do)$|"
                         r"^(?:turn\s+on|enable|switch\s+to)\s+(?P<value2>dark|light)\s+mode$", re.IGNORECASE)),
    ("radio", re.compile(r"^(?P<radio>wi-?fi|bluetooth)\s+(?:ko\s+)?(?P<value>on|off|band|chalu|khol|enable|disable|"
                         r"connect)\s*(?:karo|kar do|kardo|kijiye)?$|^turn\s+(?P<value2>on|off)\s+(?:the\s+)?"
                         r"(?P<radio2>wi-?fi|bluetooth)$", re.IGNORECASE)),
    ("default_browser", re.compile(r"^(?P<value>.+?)\s+ko\s+default\s+browser\s+(?:bana do|banao|set karo|kar do)$",
                                   re.IGNORECASE)),
    # Security switches are understood as settings so the System Agent can refuse them clearly.
    ("other", re.compile(r"^(?:windows\s+)?(?P<value>(?:windows\s+)?(?:defender|firewall|anti-?virus|uac|bitlocker|"
                         r"smart\s*screen)\s+(?:ko\s+)?(?:band|off|disable|on|chalu|enable|hata|hatao))\s*"
                         r"(?:karo|kar do|kardo|do)?$", re.IGNORECASE)),
]
OPEN_SETTINGS = [
    re.compile(r"^(?:windows\s+)?settings?\s+(?:kholo|khol do|open karo)$", re.IGNORECASE),
    re.compile(r"^(?P<page>.+?)\s+(?:ki\s+|ke\s+)?settings?\s+(?:kholo|khol do|open karo|dikhao)$", re.IGNORECASE),
    re.compile(r"^open\s+(?:the\s+)?(?P<page>.+?)\s+settings$", re.IGNORECASE),
    re.compile(r"^(?P<page>windows\s+security)\s+(?:kholo|khol do|open karo)$", re.IGNORECASE),
]
_CH = r"(?P<ch>whatsapp|email|e-mail|mail)"
SEND_MESSAGE = [
    # "WhatsApp par Sara ko likho ke ..." first, so the channel is not read as part of the name.
    re.compile(rf"^{_CH}\s+(?:par|pe|se)\s+(?P<to>.+?)\s+ko\s+(?:message\s+)?(?:likho|bhejo|bhej do|karo)\s*"
               r"(?:ke|ki|:|-)?\s*(?P<text>.+)$", re.IGNORECASE),
    re.compile(rf"^(?P<to>.+?)\s+ko\s+(?:{_CH}\s+(?:par|pe|se)\s+)?(?:(?P<ch2>message|msg|paigham|whatsapp|email|"
               r"e-mail|mail)\s+)?(?:bhejo|bhej do|karo|kar do|likho|likh do)\s*(?:ke|ki|k|:|-)\s*(?P<text>.+)$",
               re.IGNORECASE),
    re.compile(rf"^(?:send|write)\s+(?:a\s+)?(?:{_CH}\s+)?(?:message\s+)?to\s+(?P<to>.+?)\s+(?:saying|that|:)\s*"
               r"(?P<text>.+)$", re.IGNORECASE),
]
DRAFT_MESSAGE = re.compile(
    rf"^(?P<to>.+?)\s+(?:ke\s+liye|ko)\s+(?:{_CH}\s+)?(?:message|msg|email|mail)\s+(?:prepare|tayyar|draft)\s+"
    r"(?:karo|kar do|kar dein)\s*(?:ke|ki|jis\s+mein|:)?\s*(?P<about>.*)$", re.IGNORECASE)
SEND_NO_TEXT = re.compile(rf"^(?P<to>.+?)\s+ko\s+(?:{_CH}\s+(?:par|pe)\s+)?(?:message|msg|whatsapp|email|mail)\s+"
                          r"(?:bhejo|bhej do|karo|kar do)$", re.IGNORECASE)
ATTACH_EMAIL = re.compile(r"^(?P<file>\S+?\.[A-Za-z0-9]{1,6})\s+(?P<to>.+?)\s+ko\s+(?:email|e-mail|mail)\s+"
                          r"(?:karo|kar do|bhejo|bhej do)$", re.IGNORECASE)
SAVE_CONTACT = [
    re.compile(r"^(?P<name>.+?)\s+ka\s+(?:whatsapp\s+|mobile\s+|phone\s+|cell\s+)?(?:number|no\.?|nambar|numbar)\s+"
               r"(?P<phone>\+?\d[\d\s\-]{6,18})\s+(?:save|add)\s*(?:karo|kar do|kar lo|lo)?$", re.IGNORECASE),
    re.compile(r"^(?P<name>.+?)\s+ka\s+(?:email|e-mail|mail)\s+(?:address\s+)?(?P<email>\S+@\S+)\s+(?:save|add)\s*"
               r"(?:karo|kar do|kar lo|lo)?$", re.IGNORECASE),
    re.compile(r"^save\s+(?P<name>.+?)(?:'s)?\s+(?:number|phone)\s+(?:as\s+)?(?P<phone>\+?\d[\d\s\-]{6,18})$",
               re.IGNORECASE),
]
LIST_CONTACTS = re.compile(r"^(?:mere\s+|nova\s+ke\s+|sab\s+)?contacts?\s+(?:dikhao|batao|ki\s+list(?:\s+dikhao)?)$|"
                           r"^(?:list|show)\s+(?:my\s+)?contacts$", re.IGNORECASE)
DELETE_CONTACT = re.compile(r"^(?P<name>.+?)\s+ko\s+contacts?\s+se\s+(?:hatao|hata do|delete karo|nikal do)$",
                            re.IGNORECASE)
_IMG = r"[^\s\"'][^\"']*?\.(?:jpe?g|png|webp|bmp|gif|tiff?|heic)"
_IMG_TARGET = rf"(?P<target>{_IMG}|{_PRON}|(?:is|us|ye|yeh|wo)\s+(?:tasveer|photo|image|picture|pic))"
EDIT_IMAGE = [
    re.compile(rf"^{_IMG_TARGET}\s+(?:par|pe)\s+(?P<rest>.+?\s+(?:lagao|laga do|likho|likh do))$", re.IGNORECASE),
    re.compile(rf"^{_IMG_TARGET}\s+(?:ko\s+)?(?P<rest>.+?)\s*(?:kar do|karo|kardo|kijiye|kar dein|bana do|banao|badal do|"
               r"badlo|ghumao|ghuma do)$", re.IGNORECASE),
    re.compile(rf"^(?P<verb>resize|convert|compress|rotate|crop|flip)\s+(?P<target>{_IMG})(?:\s+(?:to|into|by)\s+"
               r"(?P<rest>.+))?$", re.IGNORECASE),
]
IMAGE_OP_WORDS = re.compile(r"\d+\s*[x×*]\s*\d+|\d+\s*%|\b(?:png|jpe?g|webp|bmp|gif)\b|compress|ghum|rotate|flip|mirror|"
                            r"black\s*(?:and|&)\s*white|grayscale|watermark|caption|instagram|thumbnail|story|\bdp\b|"
                            r"\bsize\b|chhot|crop", re.IGNORECASE)
_KINDS = (r"instagram\s+post|instagram\s+story|insta\s+post|youtube\s+thumbnail|facebook\s+post|facebook\s+cover|"
          r"whatsapp\s+status|visiting\s+card|post|story|banner|thumbnail|poster|flyer|card|status|dp|wallpaper")
_STYLE = r"(?P<style>(?:[a-z]+\s+){0,3}?)"
CREATE_DESIGN = [
    re.compile(rf"^(?:ek\s+)?{_STYLE}(?P<kind>{_KINDS})\s+(?:design\s+)?(?:banao|bana do|tayyar karo|design karo)\s+"
               rf"(?:jis|jismein|jis\s+mein|jis\s+par)\s*(?:par|pe|mein)?\s*{_Q}(?P<text>.+?){_Q}\s+(?:likha\s+ho|likho|ho)$",
               re.IGNORECASE),
    re.compile(rf"^{_Q}(?P<text>[^\"'“”]+?){_Q}\s+(?:ka|ki|ke\s+liye)\s+(?:ek\s+)?{_STYLE}(?P<kind>{_KINDS})\s+"
               r"(?:banao|bana do|design karo|tayyar karo)$", re.IGNORECASE),
    re.compile(rf"^(?:make|create|design)\s+(?:a|an)\s+{_STYLE}(?P<kind>{_KINDS})\s+(?:that\s+says|saying|with\s+"
               rf"(?:the\s+)?text)\s+{_Q}(?P<text>.+?){_Q}$", re.IGNORECASE),
    re.compile(rf"^(?:ek\s+)?{_STYLE}(?P<kind>{_KINDS})\s+(?:design\s+)?(?:banao|bana do|design karo)$", re.IGNORECASE),
]
_APPS = r"photoshop|ms\s*paint|paint|illustrator|gimp|word|excel|powerpoint|notepad|vs\s*code"
OPEN_WITH = [
    re.compile(rf"^(?P<target>.+?)\s+(?:ko\s+)?(?P<app>{_APPS})\s+(?:mein|me|se)\s+(?:kholo|khol do|open karo|open kar do|"
               r"edit karo)$", re.IGNORECASE),
    re.compile(rf"^open\s+(?P<target>.+?)\s+(?:in|with)\s+(?P<app>{_APPS})$", re.IGNORECASE),
]

# ---- memory, history, workflows (Phase 9) --------------------------------------------------
_REMEMBER = r"(?:yaad\s+(?:rakho|rakhna|rakh\s+lo|kar\s+lo|karlo)|remember)"
_THIS = r"(?:ye|yeh|is\s+baat\s+ko|isko|is\s+ko|ye\s+baat|yeh\s+baat|this|that)"
REMEMBER_FACT = [
    re.compile(rf"^{_THIS}\s+{_REMEMBER}$", re.IGNORECASE),  # "ye yaad rakho": what was said just before
    re.compile(rf"^(?:please\s+)?{_REMEMBER}(?:\s+(?:ke|ki|k|that)\s+|\s*[:\-]\s*|\s+)(?P<fact>.+)$", re.IGNORECASE),
    # "... yaad rakhna" at the end (Roman Urdu only: "do you remember" is a question, not a request)
    re.compile(rf"^(?P<fact>.+?)\s*[,:-]?\s+(?:{_THIS}\s+)?yaad\s+(?:rakho|rakhna|rakh\s+lo|kar\s+lo|karlo)$", re.IGNORECASE),
    re.compile(r"^یاد\s+(?:رکھو|رکھنا|رکھ\s+لو)\s+(?:کہ|کے)\s+(?P<fact>.+)$"),
    re.compile(r"^याद\s+(?:रखो|रखना|रख\s+लो)\s+(?:कि|के)\s+(?P<fact>.+)$"),
]
_YAAD = r"(?:yaad|yad)"
RECALL_MEMORY = [
    (re.compile(rf"^(?:(?:tum(?:he|hein|hen)?|aap\s+ko|nova\s+ko)\s+)?(?:mere\s+(?:baare|bare)\s+mein\s+)?kya\s+(?:kya\s+)?"
                rf"{_YAAD}\s+hai$|^(?:meri|mere|apni)\s+(?:yaadein|yaaden|memories|memory)\s+(?:dikhao|batao)$|"
                r"^(?:show|list)\s+(?:my\s+)?memories$|^what\s+do\s+you\s+remember(?:\s+about\s+me)?$", re.IGNORECASE), ""),
    (re.compile(r"^(?:mera|meraa)\s+naam\s+kya\s+hai$|^what(?:'s|\s+is)\s+my\s+name$|^میرا\s+نام\s+کیا\s+ہے$",
                re.IGNORECASE), "naam"),
    (re.compile(r"^main\s+kahan\s+(?:rehta|rehti|rahta|rahti)\s+(?:hoon|hun|hu)$|^where\s+do\s+i\s+live$",
                re.IGNORECASE), "shehar"),
    (re.compile(r"^(?:meri|mera)\s+(?:birthday|salgirah|saalgirah|janamdin)\s+kab\s+(?:hai|hoti\s+hai|aati\s+hai)$|"
                r"^when\s+is\s+my\s+birthday$", re.IGNORECASE), "birthday"),
    (re.compile(rf"^(?:kya\s+)?(?:(?:tum(?:he|hein)?|aap\s+ko)\s+)?{_YAAD}\s+hai\s+(?:ke|ki|k)\s+(?P<query>.+?)$",
                re.IGNORECASE), None),
    (re.compile(rf"^(?P<query>.+?)\s+ke\s+(?:baare|bare)\s+mein\s+(?:(?:tumhe|tumhein|aap\s+ko)\s+)?kya\s+{_YAAD}\s+hai$",
                re.IGNORECASE), None),
]
_FORGET = r"(?:bhool\s+jao|bhul\s+jao|bhool\s+jaao|bhula\s+do)"
FORGET_MEMORY = [
    (re.compile(rf"^(?:sab|saari|sari|tamam)\s+(?:yaadein|yaaden|memories|baatein)\s+(?:{_FORGET}|mita\s+do|mitao|"
                rf"delete\s+karo)$|^(?:sab\s+kuch|sab)\s+{_FORGET}$|^forget\s+everything$", re.IGNORECASE), "all"),
    (re.compile(rf"^(?:pichli\s+baatein|ye\s+conversation|conversation)\s+(?:{_FORGET}|reset\s+karo|chhoro|chhor\s+do)$|"
                r"^(?:naya|new)\s+topic$", re.IGNORECASE), "conversation"),
    (re.compile(rf"^{_THIS}\s+{_FORGET}$|^forget\s+(?:it|that)$", re.IGNORECASE), "last"),
    (re.compile(rf"^(?:{_FORGET}|forget)\s*(?:ke|ki|that|:)?\s+(?P<query>.+)$", re.IGNORECASE), None),
    (re.compile(rf"^(?P<query>.+?)\s+(?:wali\s+baat\s+)?(?:{_FORGET}|yaad\s+se\s+(?:mita\s+do|hata\s+do)|memory\s+se\s+"
                r"(?:hatao|hata\s+do|mita\s+do))$", re.IGNORECASE), None),
]
_PERIOD = (r"(?P<period>aaj|kal|parson|is\s+hafte|pichle\s+hafte|is\s+mahine|pichle\s+mahine|today|yesterday|"
           r"this\s+week|last\s+week)")
_HISTORY = r"(?:history|conversation\s+history|chat\s+history|purani\s+baatein|pichli\s+baatein)"
SEARCH_HISTORY = [
    re.compile(rf"^(?:(?:main(?:ne)?|maine|hum(?:ne)?)\s+)?{_PERIOD}\s+(?:(?:main(?:ne)?|maine|hum(?:ne)?|tum(?:ne)?|"
               r"nova\s+ne)\s+)?(?P<query>.*?)\s*kya\s+(?:kya\s+)?(?:kaha|kiya|kia|baat\s+ki|poocha|pucha|karwaya|"
               r"kaam\s+kiya)(?:\s+(?:tha|thi|the|hai))?$", re.IGNORECASE),
    re.compile(rf"^{_HISTORY}\s+(?:mein|me)\s+(?P<query>.+?)\s+(?:dhoondo|dhundo|search\s+karo|talash\s+karo)$",
               re.IGNORECASE),
    re.compile(rf"^(?:{_PERIOD}\s+ki\s+|meri\s+)?{_HISTORY}\s+(?:dikhao|batao)$|^(?:show\s+)?(?:my\s+)?history$",
               re.IGNORECASE),
    re.compile(r"^(?:pichla|aakhri|last)\s+(?:kaam|command)\s+kya\s+(?:tha|thi)$", re.IGNORECASE),
]
CLEAR_HISTORY = [
    re.compile(rf"^(?:{_PERIOD}\s+ki\s+|saari\s+|sari\s+|poori\s+|meri\s+)?{_HISTORY}\s+(?:mita\s+do|mitao|delete\s+karo|"
               r"delete\s+kar\s+do|saaf\s+karo|saaf\s+kar\s+do|clear\s+karo|hata\s+do)$|^(?:clear|delete)\s+(?:my\s+)?"
               r"(?:chat\s+|conversation\s+)?history$", re.IGNORECASE),
]
_WF = r"(?:workflow|routine)"
_WF_NAME = r"(?P<name>[\w\s-]{1,30}?)"
SAVE_WORKFLOW = [
    (re.compile(rf"^(?:naya\s+|ek\s+)?{_WF}\s+(?:banao|bana\s+do|save\s+karo)\s*[:\-]?\s*{_Q}{_WF_NAME}{_Q}\s*[:\-—]\s*"
                r"(?P<steps>.+)$", re.IGNORECASE), "replace"),
    (re.compile(rf"^(?:naya\s+|ek\s+|mera\s+|new\s+)?{_Q}{_WF_NAME}{_Q}\s+(?:naam\s+ka\s+)?{_WF}\s+(?:banao|bana\s+do|"
                r"save\s+karo)\s*(?:[:\-—]|jis\s+mein|jismein)?\s*(?P<steps>.*?)(?:\s+(?:hon|ho|khulein|kholo))?$",
                re.IGNORECASE), "replace"),
    (re.compile(rf"^{_WF_NAME}\s+{_WF}\s+(?:mein|me)\s+(?P<steps>.+?)\s+(?:bhi\s+)?(?:add\s+karo|add\s+kar\s+do|daal\s+do|"
                r"dalo|shamil\s+karo)$", re.IGNORECASE), "add"),
    (re.compile(rf"^{_WF_NAME}\s+{_WF}\s+se\s+(?P<steps>.+?)\s+(?:hata\s+do|hatao|nikal\s+do|remove\s+karo)$",
                re.IGNORECASE), "remove"),
    (re.compile(rf"^{_WF_NAME}\s+{_WF}\s+(?:badlo|badal\s+do|change\s+karo|dobara\s+set\s+karo|edit\s+karo)$",
                re.IGNORECASE), "replace"),
]
LIST_WORKFLOWS = re.compile(rf"^(?:mere\s+|sab\s+|saare\s+)?{_WF}s?\s+(?:dikhao|batao)$|^(?:mere|my)\s+{_WF}s?\s+(?:kya|"
                            rf"kaun\s+se)\s+hain$|^(?:list|show)\s+(?:my\s+)?{_WF}s$", re.IGNORECASE)
DELETE_WORKFLOW = re.compile(rf"^{_WF_NAME}\s+{_WF}\s+(?:delete\s+karo|delete\s+kar\s+do|mita\s+do|mitao|hata\s+do|"
                             r"hatao)$", re.IGNORECASE)
REPEAT_LAST = [
    (re.compile(r"^(?:(?:wahi|wohi|yehi|pichla|pichli)\s+)?(?:(?:kaam|command)\s+)?(?:dobara|phir\s+se|again|repeat)\s+"
                r"(?:karo|kar\s+do|kardo|chalao|chala\s+do)$|^do\s+it\s+again$|^repeat\s+(?:that|the\s+last\s+command)$",
                re.IGNORECASE), "command"),
    (re.compile(r"^(?:kya\s+kaha|dobara\s+(?:bolo|batao|kaho)|phir\s+se\s+(?:bolo|batao)|say\s+(?:that|it)\s+again|"
                r"repeat\s+what\s+you\s+said)$", re.IGNORECASE), "response"),
]
PERIOD_KEYS = {"aaj": "today", "today": "today", "kal": "yesterday", "yesterday": "yesterday", "parson": "before_yesterday",
               "is hafte": "week", "pichle hafte": "week", "this week": "week", "last week": "week",
               "is mahine": "month", "pichle mahine": "month"}

# Whole commands whose text may contain "aur"/"and" that must not split them into several commands.
UNSPLITTABLE = [CREATE_FILE_WITH_TEXT, *EDIT_REPLACE, *EDIT_APPEND, *MODIFY_CODE, *EXPLAIN_ERROR, *SEND_MESSAGE,
                DRAFT_MESSAGE, *CREATE_DESIGN[:3], EDIT_IMAGE[0], *REMEMBER_FACT[1:3],
                *(p for p, _ in SAVE_WORKFLOW[:4])]


def _settings_intent(cleaned: str) -> tuple[str, dict[str, object]] | None:
    for setting, pattern in SETTING_RULES:
        if not (m := pattern.search(cleaned)):
            continue
        groups = {k: v for k, v in m.groupdict().items() if v}
        value = groups.get("value") or groups.get("value2") or ""
        if setting in ("volume", "brightness") and not _LEVEL_WORDS.search(value):
            continue  # "awaaz kaisi hai" is not a change
        if setting == "radio":
            setting = (groups.get("radio") or groups.get("radio2") or "").lower().replace("-", "")
        if setting == "other":
            return "change_setting", {"setting": "other", "request": cleaned}
        return "change_setting", {"setting": setting, "value": value.strip()}
    for pattern in OPEN_SETTINGS:
        if m := pattern.search(cleaned):
            return "open_settings", {"page": _target_text(m.groupdict().get("page"))}
    return None


def _comm_intent(cleaned: str) -> tuple[str, dict[str, object]] | None:
    def channel(m: re.Match[str]) -> str | None:
        words = " ".join(filter(None, [m.groupdict().get("ch"), m.groupdict().get("ch2")])).lower()
        return "email" if "mail" in words else ("whatsapp" if "whatsapp" in words else None)

    if LIST_CONTACTS.search(cleaned):
        return "list_contacts", {}
    for pattern in SAVE_CONTACT:
        if m := pattern.search(cleaned):
            return "save_contact", {"name": _target_text(m.group("name")), **{k: v.strip() for k, v in
                                                                                m.groupdict().items()
                                                                                if k in ("phone", "email") and v}}
    if m := DELETE_CONTACT.search(cleaned):
        return "delete_contact", {"name": _target_text(m.group("name"))}
    if m := ATTACH_EMAIL.search(cleaned):
        return "send_message", {"channel": "email", "recipient": _target_text(m.group("to")),
                                "attachment": m.group("file"), "text": f"{m.group('file')} attach hai."}
    if m := DRAFT_MESSAGE.search(cleaned):
        about = m.group("about").strip()
        return "send_message", {"recipient": _target_text(m.group("to")), "channel": channel(m), "draft_only": True,
                                **({"instruction": about} if about else {})}
    for pattern in SEND_MESSAGE:
        if m := pattern.search(cleaned):
            text, _quoted_text = _quoted(m.group("text"))
            return "send_message", {"recipient": _target_text(m.group("to")), "channel": channel(m), "text": text}
    if m := SEND_NO_TEXT.search(cleaned):
        return "send_message", {"recipient": _target_text(m.group("to")), "channel": channel(m)}
    return None


def _design_intent(cleaned: str) -> tuple[str, dict[str, object]] | None:
    for pattern in OPEN_WITH:
        if (m := pattern.search(cleaned)) and _fileish(m.group("target")):
            return "open_with", {"target": _target_text(m.group("target")),
                                 "app": re.sub(r"\s+", " ", m.group("app").lower()).replace("ms paint", "paint")}
    for pattern in CREATE_DESIGN:
        if m := pattern.search(cleaned):
            text = m.groupdict().get("text")
            return "create_design", {"kind": " ".join(m.group("kind").lower().split()).replace("insta ", "instagram "),
                                     **({"text": text.strip()} if text else {}),
                                     **({"style": m.group("style").strip()} if (m.group("style") or "").strip() else {})}
    for pattern in EDIT_IMAGE:
        if m := pattern.search(cleaned):
            # Everything after the file name (verb included): "90 degree ghumao" needs "ghumao" to mean rotate.
            rest = " ".join(filter(None, [m.groupdict().get("verb"), cleaned[m.end("target"):]]))
            target = m.group("target")
            if not re.search(_IMG + "$", target, re.IGNORECASE) and not IMAGE_OP_WORDS.search(rest):
                continue  # "isko band kar do" is not a picture edit
            return "edit_image", {"target": _target_text(target), "request": rest.strip()}
    return None


def _memory_intent(cleaned: str) -> tuple[str, dict[str, object]] | None:
    for p, what in REPEAT_LAST:
        if p.search(cleaned):
            return "repeat_last", {"what": what}
    for p, query in RECALL_MEMORY:  # before "remember": "kya tumhe yaad hai ke ..." is a question
        if m := p.search(cleaned):
            return "recall_memory", {"query": query if query is not None else _target_text(m.group("query")) or ""}
    for p in REMEMBER_FACT:
        if m := p.search(cleaned):
            fact = (m.groupdict().get("fact") or "").strip(" ,:-\"'“”")
            return "remember_fact", {"fact": fact, "explicit": True}
    for p, kind in FORGET_MEMORY:
        if m := p.search(cleaned):
            if kind == "all":
                return "forget_memory", {"all": True}
            if kind == "conversation":
                return "forget_memory", {"scope": "conversation"}
            return "forget_memory", {"query": "" if kind == "last" else _target_text(m.group("query")) or ""}
    for p in CLEAR_HISTORY:
        if m := p.search(cleaned):
            period = PERIOD_KEYS.get(" ".join((m.groupdict().get("period") or "").lower().split()), "")
            return "clear_history", {"period": period}
    for p in SEARCH_HISTORY:
        if m := p.search(cleaned):
            groups = m.groupdict()
            period = PERIOD_KEYS.get(" ".join((groups.get("period") or "").lower().split()), "")
            return "search_history", {"query": (groups.get("query") or "").strip(), "period": period}
    if LIST_WORKFLOWS.search(cleaned):
        return "list_workflows", {}
    for p, action in SAVE_WORKFLOW:
        if m := p.search(cleaned):
            return "save_workflow", {"workflow": _target_text(m.group("name")), "steps": (m.group("steps") or "").strip()
                                     if "steps" in m.groupdict() else "", "edit_action": action}
    if m := DELETE_WORKFLOW.search(cleaned):
        return "delete_workflow", {"workflow": _target_text(m.group("name"))}
    if fact := detect_fact(cleaned):  # "mera naam Ahmed hai": NOVA offers to remember it
        return "remember_fact", {"fact": fact.text, "explicit": False}
    return None


def _target_text(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"^(?:(?:zara|please|plz|meri|mera|mere|my|the)\s+)+", "", value.strip(), flags=re.IGNORECASE)
    return value.strip(" \"'“”‘’") or None


def _ext_ok(name: str) -> bool:
    """Has a file extension that is not a website ending ("notes.txt" yes, "example.com" no)."""
    m = re.search(r"\.([A-Za-z0-9]{1,8})$", name.strip())
    return bool(m) and m.group(1).lower() not in _WEB_TLDS


def _fileish(target: str | None) -> bool:
    t = (target or "").strip().lower()
    if not t:
        return False
    return bool(re.fullmatch(_PRON, t) or t in ("is", "us", "in", "un") or _ORDINAL_TARGET.match(t) or _ext_ok(t)
                or _FILE_WORD.search(t)
                or re.match(r"^[a-z]:\\", t) or _FOLDER_WORDS.match(t))


def _folderish(loc: str | None) -> bool:
    t = (loc or "").strip().lower()
    t = re.sub(r"^(?:mera|meri|mere|my|the)\s+", "", t)
    return bool(_FOLDER_WORDS.match(re.sub(r"\s+folder$", "", t)) or t.endswith((" folder", " project"))
                or re.match(r"^[a-z]:\\", t) or re.fullmatch(r"(?:is|us|ye|yeh|wo)\s+folder", t))


def _quoted(text: str) -> tuple[str, bool]:
    t = text.strip()
    if len(t) >= 2 and t[0] in "\"'“‘" and t[-1] in "\"'”’":
        return t[1:-1], True
    return t, False


def _coding_intent(cleaned: str) -> tuple[str, dict[str, object]] | None:
    def project(m: re.Match[str]) -> dict[str, object]:
        p = _target_text(m.groupdict().get("p"))
        return {"project": re.sub(r"\s+project$", "", p, flags=re.IGNORECASE)} if p else {}

    if LIST_PROJECTS.search(cleaned):
        return "inspect_project", {}
    for p in OPEN_PROJECT:
        if m := p.search(cleaned):
            return "open_project", project(m)
    for p in INSPECT_PROJECT:
        if m := p.search(cleaned):
            return "inspect_project", project(m)
    for p in RUN_TESTS:
        if m := p.search(cleaned):
            return "run_tests", project(m)
    for p in CHECK_ERRORS:
        if m := p.search(cleaned):
            return "check_errors", project(m)
    for p in RUN_COMMAND:
        if m := p.search(cleaned):
            return "run_command", {**project(m), "command": " ".join(m.group("cmd").split())}
    for p in EXPLAIN_ERROR:
        if m := p.search(cleaned):
            return "explain_error", {"text": m.group("text").strip()} if m.group("text") else {}
    for p in FIX_ERROR:
        if p.search(cleaned):
            return "fix_error", {}
    return None


def _file_intent(cleaned: str) -> tuple[str, dict[str, object]] | None:
    # "isko Documents mein move karo" -> "is ko ...", so "X ko Y mein ..." patterns see the pronoun as X.
    split_ko = re.sub(r"^(is|us|in|un)ko\b", r"\1 ko", cleaned, flags=re.IGNORECASE)
    for p in UNDO_FILE:
        if p.search(cleaned):
            return "undo_file_op", {}
    if m := CREATE_FILE_WITH_TEXT.search(cleaned):
        return "create_file", {"file_name": m.group("name").strip(), "location": _target_text(m.group("loc")),
                               "text": _quoted(m.group("text"))[0]}
    for p in EDIT_REPLACE:
        if m := p.search(cleaned):
            target = m.groupdict().get("target") or m.groupdict().get("target2")
            if target:
                return "edit_file", {"target": _target_text(target), "edit_action": "replace",
                                     "old_text": m.group("old").strip(), "new_text": m.group("new").strip()}
    for p in EDIT_APPEND:
        if m := p.search(cleaned):
            target = _target_text(m.group("target")) or ""
            text, quoted = _quoted(m.group("text"))
            if re.search(rf"\.(?:{_CODE_EXT})$", target, re.IGNORECASE) and not quoted:
                return "modify_code", {"target": target, "instruction": cleaned}  # "app.py mein login function add karo"
            return "edit_file", {"target": target, "edit_action": "append", "text": text}
    for p in SEARCH_FILES:
        if m := p.search(cleaned):
            q = re.sub(r"^(?:saari|sari|sab|saare|all|meri|mere|my)\s*", "", m.group("q").strip(), flags=re.IGNORECASE)
            loc = _target_text(m.groupdict().get("loc"))
            if not loc and _FOLDER_WORDS.match(q):  # "Downloads ki files dikhao": list that folder
                return "read_file", {"target": q}
            if q:
                return "search_files", {"query": q.strip(" \"'"), "location": loc}
    for p in CREATE_FILE:
        if m := p.search(cleaned):
            return "create_file", {"file_name": _target_text(m.group("name")), "location": _target_text(m.group("loc"))}
    for p in CREATE_FOLDER_AT:
        if m := p.search(cleaned):
            name = _target_text(m.group("name"))
            if name and name.lower() in FOLDER_DETERMINERS:
                name = None
            return "create_folder", {"folder_name": name, "location": _target_text(m.group("loc"))}
    for p in READ_FILE_SUMMARY:
        if m := p.search(cleaned):
            return "read_file", {"target": _target_text(m.group("target")), "summary": True}
    for p in READ_FILE:
        if (m := p.search(cleaned)) and (_fileish(m.group("target")) or _folderish(m.group("target"))):
            return "read_file", {"target": _target_text(m.group("target"))}
    for p in OPEN_FILE:
        if (m := p.search(cleaned)) and (_ext_ok(m.group("target")) or _FILE_WORD.search(m.group("target"))):
            return "open_file", {"target": _target_text(m.group("target"))}
    for p in RENAME_FILE:
        if (m := p.search(cleaned)) and _fileish(m.group("target")):
            return "rename_file", {"target": _target_text(m.group("target")), "new_name": _target_text(m.group("new"))}
    for p in MOVE_FILE:
        if (m := p.search(split_ko)) and _fileish(m.group("target")):
            return "move_file", {"target": _target_text(m.group("target")), "destination": _target_text(m.group("dest"))}
    for p in COPY_FILE:
        if (m := p.search(split_ko)) and _fileish(m.group("target")):
            return "copy_file", {"target": _target_text(m.group("target")),
                                 "destination": _target_text(m.groupdict().get("dest"))}
    for p in DELETE_FILE:
        if (m := p.search(cleaned)) and _fileish(m.group("target")):
            return "delete_file", {"target": _target_text(m.group("target"))}
    for p in ORGANIZE_FOLDER:
        if (m := p.search(cleaned)) and _folderish(m.group("loc")):
            return "organize_folder", {"location": _target_text(m.group("loc"))}
    for p in FOLDER_REPORT:
        if (m := p.search(cleaned)) and _folderish(m.group("loc")):
            return "folder_report", {"location": _target_text(m.group("loc"))}
    for p in MODIFY_CODE:
        if m := p.search(cleaned):
            return "modify_code", {"target": m.group("target"), "instruction": cleaned,
                                   **({"project": _target_text(m.group("p"))} if m.groupdict().get("p") else {})}
    return None


def _computer_intent(cleaned: str) -> tuple[str, dict[str, object]] | None:
    """Action commands. Explicit dictation ("likho: ...") is checked first so dictated text is never treated as
    a command; file/coding and browser commands come before the ambiguous trailing "... likho" form."""
    for p in TYPE_TEXT[:2]:
        if m := p.search(cleaned):
            return "type_text", {"text": m.group("text").strip()}
    # Settings first: "awaaz band karo" / "wifi band karo" are settings, not "close the app called awaaz".
    if setting := _settings_intent(cleaned):
        return setting
    if coding := _coding_intent(cleaned):
        return coding
    if message := _comm_intent(cleaned):
        return message
    if design := _design_intent(cleaned):
        return design
    if files := _file_intent(cleaned):
        return files
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
    r"|^start\s+(?:my\s+)?(?P<name2>work(?:\s+environment)?)$"
    r"|^(?:mera\s+|meri\s+|my\s+)?(?P<name3>[\w\s-]{1,30}?)\s+(?:workflow|routine)\s+(?:chalao|chala do|start karo|shuru karo|"
    r"run karo|kholo)$|^(?:run|start)\s+(?:the\s+|my\s+)?(?P<name4>[\w\s-]{1,30}?)\s+(?:workflow|routine)$",
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

    async def understand(self, text: str, context: list[ConversationTurn] | None = None,
                         memories: list[str] | None = None) -> Understanding:
        """Splits compound commands ("Chrome kholo aur RAM batao") when every part is understood."""
        cleaned = normalize(text, self._wake)
        # Explicit dictation ("likho: main aur tum", "type hello and bye") is never split into commands, nor is
        # text going into a file or a code change. The trailing form ("... type karo") is ambiguous, so it may
        # still be one part of a compound.
        dictation = any(p.search(cleaned) for p in TYPE_TEXT[:2])
        whole = dictation or any(p.search(cleaned) for p in UNSPLITTABLE)
        parts = [] if whole else [p for p in COMPOUND_SPLIT.split(cleaned) if p.strip()]
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
        # which lets hybrid mode hand them to the LLM. A command carrying text ("notes.txt mein likho: ...",
        # "... banao aur us mein ... likho") is long because of that text, not because it is unclear.
        carries_text = any(p.search(cleaned) for p in TYPE_TEXT[:2]) or any(p.search(cleaned) for p in UNSPLITTABLE)
        damping = 0.75 if len(cleaned.split()) > 8 and not carries_text else 1.0

        def make(name: str, confidence: float, /, **entities: object) -> Intent:  # "/": an entity may be called "name"
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
            name = next(g for g in (m["name"], m["name2"], m["name3"], m["name4"]) if g)
            return make("run_workflow", 0.85, workflow=" ".join(name.lower().split()))

        if not any(p.search(cleaned) for p in TYPE_TEXT[:2]) and (memory := _memory_intent(cleaned)):
            name, entities = memory
            return make(name, 0.85, **entities)

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
