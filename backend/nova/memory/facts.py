"""Long-term memory facts: what the user told NOVA to remember, and which statements are worth suggesting.

A few facts fill a "slot" (name, city, work, birthday): saying a new name replaces the old one, and NOVA uses the
name to address the user. Everything else is kept in the user's own words. Secrets are never stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

MAX_FACT_CHARS = 300
MIN_FACT_CHARS = 3

_END = r"[\s.!۔]*$"
# (slot or None, pattern with a "v" group for the value). Statements only - questions never match.
FACT_PATTERNS: list[tuple[str | None, re.Pattern[str]]] = [
    (slot, re.compile(pattern + _END, re.IGNORECASE)) for slot, pattern in [
        ("name", r"^(?:mera|meraa)\s+naam\s+(?P<v>[^\d,.!?]{2,40}?)\s+(?:hai|he|h)"),
        ("name", r"^my\s+name\s+is\s+(?P<v>[^\d,.!?]{2,40})"),
        ("name", r"^(?:mujhe|mujhay)\s+(?P<v>[^\d,.!?]{2,30}?)\s+(?:kaha|bulaya|pukara)\s+(?:karo|kijiye|karein|karna)"),
        ("name", r"^call\s+me\s+(?P<v>[^\d,.!?]{2,30})"),
        ("name", r"^میرا\s+نام\s+(?P<v>[^\d،.!?]{2,40}?)\s+ہے"),
        ("name", r"^मेरा\s+नाम\s+(?P<v>[^\d,.!?]{2,40}?)\s+है"),
        ("city", r"^main\s+(?P<v>[a-z][a-z\s]{1,30}?)\s+(?:mein|me|main)\s+(?:rehta|rehti|rahta|rahti)\s+(?:hoon|hun|hu)"),
        ("city", r"^i\s+live\s+in\s+(?P<v>[a-z][a-z\s]{1,30})"),
        ("work", r"^main\s+(?P<v>.{2,40}?)\s+(?:mein|me|par)\s+(?:kaam|job)\s+(?:karta|karti)\s+(?:hoon|hun|hu)"),
        ("work", r"^(?:meri|mera)\s+(?:company|business|office)\s+(?:ka\s+naam\s+)?(?P<v>.{2,40}?)\s+(?:hai|he)"),
        ("work", r"^i\s+work\s+(?:at|for|in)\s+(?P<v>.{2,40})"),
        ("birthday", r"^(?:meri|mera)\s+(?:birthday|salgirah|saalgirah|janamdin|janam\s+din)\s+(?P<v>.{2,30}?)\s+"
                     r"(?:ko\s+)?(?:hai|hoti\s+hai|he)"),
        ("birthday", r"^my\s+birthday\s+is\s+(?:on\s+)?(?P<v>.{2,30})"),
        (None, r"^(?:mujhe|mujhay)\s+(?P<v>.{2,50}?)\s+(?:bohat\s+|bahut\s+|zyada\s+|sab\s+se\s+zyada\s+)?"
               r"(?:pasand|achha|acha|achhi|achi)\s+(?:hai|hain|lagta\s+hai|lagti\s+hai|lagte\s+hain)"),
        (None, r"^(?:mujhe|mujhay)\s+(?P<v>.{2,50}?)\s+(?:bilkul\s+)?(?:pasand\s+nahi|nahi\s+pasand|bura\s+lagta|"
               r"buri\s+lagti)\s*(?:hai|hain)?"),
        (None, r"^i\s+(?:really\s+)?(?:like|love|prefer|hate|don'?t\s+like)\s+(?P<v>.{2,50})"),
    ]
]
# Values that make a "fact" a question or a vague reference ("mera naam kya hai", "mujhe ye pasand hai").
NOT_A_VALUE = re.compile(r"^(?:ye|yeh|wo|woh|is|us|isko|usko|this|that|it)\b|\b(?:kya|kaun|kaunsa|kaun\s+sa|kitna|"
                         r"kitni|kab|kahan|kaise|what|which|who|where|when|how)\b|\?", re.IGNORECASE)
# Things NOVA never keeps in memory: passwords, PINs, OTPs, card/CNIC/IBAN/account numbers, keys, long numbers.
SECRET_TEXT = re.compile(
    r"\b(?:password|passwd|pass\s*word|pin|pin\s*code|otp|cvv|cvc|card\s*number|cnic|iban|account\s*(?:number|no)|"
    r"khata\s*(?:number|nambar)|api\s*key|secret\s*key|token)\b|\b\d{11,19}\b|\b\d{5}-\d{7}-\d\b|"
    r"پاس\s*ورڈ|पासवर्ड",
    re.IGNORECASE,
)
REMINDER = re.compile(r"\byaad\s+(?:dila|dilana|dilao|dila\s+dena)\b|\bremind\s+me\b", re.IGNORECASE)
REMEMBER_REQUEST = re.compile(r"\byaad\s+(?:rakh|kar\s+lo)|\bremember\b|\bbhool\s+jao\b|یاد\s+رکھ|याद\s+रख", re.IGNORECASE)

# Words that carry no meaning for matching ("mera", "hai", "the").
STOPWORDS = set("""
hai hain he h ka ki ke ko mein me main se par pe aur ya kya mera meri mere mujhe hum tum aap ye yeh wo woh is us
tha thi the ho hon nahi bhi to hi ek jo jab kab kahan kaun kaise kitna liye wala wali wale baat baare bare yaad
the a an of to and or is are was my me i you it this that in on at for with do does what about
""".split())
# Words that mean the same thing when recalling ("salgirah" finds a "birthday" memory).
SYNONYMS = [
    {"naam", "name"},
    {"birthday", "salgirah", "saalgirah", "janamdin", "birth"},
    {"shehar", "city", "rehta", "rehti", "rahta", "rahti", "live"},
    {"kaam", "job", "company", "office", "business", "work"},
    {"pasand", "like", "love", "favourite", "favorite"},
    {"biwi", "wife", "begum"},
    {"shohar", "husband", "miyan"},
    {"beta", "son"},
    {"beti", "daughter"},
]
SLOT_WORDS: dict[str, re.Pattern[str]] = {
    "name": re.compile(r"\b(?:naam|name)\b", re.IGNORECASE),
    "city": re.compile(r"\b(?:shehar|city|kahan\s+(?:rehta|rehti|rahta|rahti)|where\s+do\s+i\s+live)\b", re.IGNORECASE),
    "work": re.compile(r"\b(?:company|office|job|where\s+do\s+i\s+work|kahan\s+kaam)\b", re.IGNORECASE),
    "birthday": re.compile(r"\b(?:birthday|salgirah|saalgirah|janamdin)\b", re.IGNORECASE),
}
MONTHS = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class Fact:
    text: str  # the user's own words
    slot: str | None = None  # name | city | work | birthday
    value: str | None = None  # the slot's value ("Ahmed")


def clean(text: str) -> str:
    return " ".join(str(text or "").split()).strip(" \"'“”‘’")


def norm(text: str) -> str:
    """For duplicate checks: case, spacing and punctuation do not matter."""
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


def detect_fact(text: str) -> Fact | None:
    """A lasting personal statement worth remembering ("mera naam Ahmed hai"), or None."""
    t = clean(text)
    for slot, pattern in FACT_PATTERNS:
        m = pattern.match(t)
        if not m:
            continue
        value = clean(m.group("v"))
        if not value or NOT_A_VALUE.search(value):
            return None
        if slot == "name":
            value = value.title() if value.islower() else value
        return Fact(t, slot, value)
    return None


def to_fact(text: str) -> Fact:
    """A fact the user asked to remember: its slot when it is one ("mera naam Ahmed hai"), else free text."""
    t = clean(text)
    found = detect_fact(t)
    return found if found else Fact(t)


def problem(text: str) -> str | None:
    """Why a fact cannot be stored (Roman Urdu), or None."""
    t = clean(text)
    if len(t) < MIN_FACT_CHARS:
        return "Kya yaad rakhoon? Kahein: \"yaad rakho ke ...\""
    if len(t) > MAX_FACT_CHARS:
        return f"Ye baat bohat lambi hai — {MAX_FACT_CHARS} haroof tak yaad rakh sakta hoon."
    if SECRET_TEXT.search(t):
        return ("Is baat mein password, PIN, card, CNIC ya account number jaisi cheez lagti hai — NOVA aisi cheezein "
                "yaad nahi rakhta (inhein kisi password manager mein rakhein). Phone number ke liye Contacts hain.")
    return None


def words(text: str) -> set[str]:
    out: set[str] = set()
    for w in re.findall(r"\w+", text.lower()):
        if len(w) < 3 or w in STOPWORDS:
            continue
        out.add(w)
        for group in SYNONYMS:
            if w in group:
                out |= group
    return out


def slot_of(query: str) -> str | None:
    for slot, pattern in SLOT_WORDS.items():
        if pattern.search(query):
            return slot
    return None


def rank(query: str, memories: list[dict], limit: int = 5) -> list[dict]:
    """The memories that share the most words with the query (newest first). Only the best-matching ones:
    "nova meeting wali baat" must not also pick another memory that merely shares "nova"."""
    want = words(query)
    if not want:
        return []
    scored = []
    for m in memories:
        score = len(want & words(m["text"]))
        if score:
            scored.append((score, m["id"], m))
    if not scored:
        return []
    best = max(s[0] for s in scored)
    scored = sorted((s for s in scored if s[0] == best), key=lambda s: s[1], reverse=True)
    return [m for _, _, m in scored[:limit]]


def short_date(iso: str | None) -> str:
    try:
        d = datetime.fromisoformat(iso or "")
    except ValueError:
        return ""
    return f"{d.day} {MONTHS[d.month]}"
