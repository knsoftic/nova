"""Wake-word detection on transcripts, so the wake word is fully configurable.

Pre-trained wake-word models only know fixed phrases ("hey jarvis"). NOVA instead transcribes each
detected utterance locally and checks whether it starts with the wake word / assistant name, in
any script Whisper may produce: "Hey NOVA", "ہے نووا", "हे नोवा", or near-misses like "Nowa".
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from .translit import _fallback, to_urdu_script

# Whisper writes "Hey" in Urdu script in several ways ("ہی" is the most common).
# Includes Whisper's mishearings of "Hey" seen in testing ("کی", "حی"); the name itself must still match.
GREETINGS = {"hey", "hi", "hay", "he", "ok", "okay", "ae", "ay", "oye", "hello", "ہے", "ہی", "ہائے", "ہائی",
             "ہیلو", "اے", "او", "اوکے", "هی", "کی", "حی", "ہیے", "हे", "है", "ए", "हाय", "हेलो", "की"}
# Includes Whisper's mishearings of "NOVA" on cut-off speech seen in testing ("نبا", "نبہا", "نوبا").
BUILTIN_NAME_FORMS = {"nova": {"nova", "noba", "nowa", "novaa", "نووا", "نوا", "نووہ", "نوعہ", "نووَا", "نبا", "نبہا",
                               "نوبا", "नोवा", "नोबा", "नोव"}}

# Split on separators, not on \w: Python's \w misses Devanagari vowel signs ("नोवा" would break apart).
TOKEN = re.compile(r"[^\s,،.!?۔:;\-\"“”]+")
MAX_WAKE_POSITION = 3  # the name must be within the first few words


@dataclass(frozen=True)
class WakeResult:
    detected: bool
    command: str  # the text after the wake word ("" if the user only said the wake word)


def _norm(token: str) -> str:
    return token.lower().strip("'")


def _forms_of(word: str) -> set[str]:
    key = _norm(word)
    if not key:
        return set()
    return {key, *BUILTIN_NAME_FORMS.get(key, set()), _norm(to_urdu_script(word)), _fallback(word)} - {""}


def name_forms(assistant_name: str, wake_word: str) -> set[str]:
    return set().union(*(_forms_of(w) for w in assistant_name.split()))


def lead_words(assistant_name: str, wake_word: str) -> set[str]:
    """Words allowed before the name: greetings plus the rest of the wake phrase ("Suno" in "Suno Zara")."""
    names = {_norm(w) for w in assistant_name.split()}
    extra = set().union(*(_forms_of(w) for w in wake_word.split() if _norm(w) not in names)) if wake_word else set()
    return GREETINGS | extra


# Real words that look like the name to the fuzzy match ("نواب" = Nawab): never the wake word.
NOT_THE_NAME = {"نواب", "نوابی", "نوابوں"}


def _matches(token: str, forms: set[str]) -> bool:
    if token in forms:
        return True
    if token in NOT_THE_NAME:
        return False
    if len(token) < 3:
        return False
    # Fuzzy match against forms in the same script ("nowa" ~ "nova", "نووت" ~ "نووا").
    same_script = [f for f in forms if f.isascii() == token.isascii()]
    return bool(difflib.get_close_matches(token, same_script, n=1, cutoff=0.75))


def detect_wake(transcript: str, assistant_name: str = "NOVA", wake_word: str = "Hey NOVA") -> WakeResult:
    tokens = [(m.group(0), m.end()) for m in TOKEN.finditer(transcript)]
    forms = name_forms(assistant_name, wake_word)
    leads = lead_words(assistant_name, wake_word)
    for i, (token, end) in enumerate(tokens[:MAX_WAKE_POSITION + 1]):
        # Whisper sometimes splits the name ("نو وا"): try the word alone, then joined with the next one.
        candidates = [(_norm(token), end)]
        if i + 1 < len(tokens):
            candidates.append((_norm(token) + _norm(tokens[i + 1][0]), tokens[i + 1][1]))
        for word, word_end in candidates:
            if not _matches(word, forms):
                continue
            # Everything before the name must be a greeting ("hey", "ہے"), otherwise it is just a mention.
            if all(_norm(t) in leads for t, _ in tokens[:i]):
                command = transcript[word_end:].lstrip(" ,،.!?۔:;-")
                return WakeResult(True, command.strip())
    return WakeResult(False, "")
