"""Signals for estimating how the user is communicating right now - only ever an estimate.

Words and sentence form come from the command; voice signals (speaking speed, loudness, pitch) are measured from
the utterance in memory and thrown away - neither the audio nor these numbers are stored.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np

STATES = ("neutral", "frustrated", "hurried", "confused", "positive", "tired")
LABELS = {"frustrated": "pareshan", "hurried": "jaldi mein", "confused": "uljhan mein", "positive": "khush",
          "tired": "thake hue", "neutral": ""}
SAMPLE_RATE = 16_000
FRAME = 480  # 30 ms

_I = re.IGNORECASE
# (state, weight, pattern, reason shown to the user). Roman Urdu, English, Urdu script.
TEXT_SIGNALS: list[tuple[str, float, re.Pattern[str], str]] = [
    ("frustrated", 0.5, re.compile(
        r"\b(?:kitni\s+(?:dafa|baar|bar)|phir\s+se\s+(?:ghalat|nahi)|(?:kaam|chal)\s+(?:hi\s+)?nahi\s+(?:kar\s+)?"
        r"(?:raha|rahe|rahi)|bakwas|bekaar|bekar|faltu|pagal|uff+|musibat|tang\s+aa|dimagh\s+kharab|sun\s+(?:hi\s+)?"
        r"nahi\s+(?:rahe|raha)|irritat\w*|frustrat\w*|useless|stupid|wtf|annoying|ridiculous)\b|بکواس|بیکار|تنگ\s+آ", _I),
     "naraazgi wale alfaaz"),
    ("frustrated", 0.25, re.compile(r"!{2,}"), "kai \"!\""),
    ("hurried", 0.55, re.compile(
        r"\b(?:jaldi|jaldi\s+se|foran|fauran|turant|abhi\s+ke\s+abhi|quick(?:ly)?|fast|asap|hurry|der\s+ho\s+rahi|"
        r"late\s+ho\s+(?:raha|rahi|gaya|gayi))\b|جلدی|فوراً|फ़ौरन|जल्दी", _I), "jaldi wale alfaaz"),
    ("confused", 0.55, re.compile(
        r"\b(?:samajh\s+nahi\s+aa(?:ya|raha)|samjha\s+nahi|kya\s+matlab|matlab\s+kya|pata\s+nahi|kaise\s+(?:karoon|karun|"
        r"karte|hota|hoga)|kya\s+karoon|confus\w*|what\s+do\s+you\s+mean|how\s+do\s+i|i\s+don'?t\s+understand)\b"
        r"|سمجھ\s+نہیں|समझ\s+नहीं", _I), "uljhan wale alfaaz"),
    ("confused", 0.2, re.compile(r"\?{2,}|؟{2,}"), "kai \"?\""),
    ("positive", 0.7, re.compile(
        r"\b(?:shukriya|shukria|thanks?|thank\s+you|thanku|jazak\s*allah|zabardast|bohat\s+khoob|kamaal|wah|great|"
        r"awesome|perfect|shabash|(?:acha|achha)\s+kaam|nice|well\s+done)\b|شکریہ|زبردست|शुक्रिया|धन्यवाद", _I),
     "shukriya/tareef"),
    ("tired", 0.55, re.compile(
        r"\b(?:thak\s+(?:gaya|gayi|gaye)|thaka\s+hua|thaki\s+hui|neend\s+aa|tired|sleepy|exhausted)\b|تھک\s+گ", _I),
     "thakan wale alfaaz"),
]
CAPS_WORD = re.compile(r"\b[A-Z]{4,}\b")
KNOWN_CAPS = {"NOVA", "HTML", "JSON", "WIFI", "XAMPP", "HTTP", "HTTPS", "UEFI", "BIOS", "NVIDIA", "WHATSAPP", "CHROME"}
# Short, plain commands ("Chrome kholo"): the user wants it done, not explained.
POLITE = re.compile(r"\b(?:please|plz|zara|meharbani|kya\s+aap)\b", _I)


@dataclass(frozen=True)
class Signal:
    state: str
    weight: float
    reason: str


def text_signals(text: str) -> list[Signal]:
    found = [Signal(state, weight, reason) for state, weight, pattern, reason in TEXT_SIGNALS if pattern.search(text)]
    shouting = [w for w in CAPS_WORD.findall(text) if w not in KNOWN_CAPS]
    if len(shouting) >= 2:
        found.append(Signal("frustrated", 0.2, "BARE HAROOF mein likha"))
    return found


def is_simple_command(text: str) -> bool:
    return len(text.split()) <= 4 and not POLITE.search(text) and "?" not in text


@dataclass(frozen=True)
class VoiceFeatures:
    """Measured from one utterance; compared only with the same user's earlier utterances in this session."""

    duration_s: float
    voiced_s: float
    words: int
    rate_wps: float  # words per second of speech
    loudness_db: float  # mean level of voiced frames (dBFS)
    pitch_hz: float | None  # median pitch of voiced frames


def _pitch(frame: np.ndarray) -> float | None:
    """Fundamental frequency of one voiced frame by autocorrelation (75-400 Hz), or None."""
    x = frame - frame.mean()
    energy = float(np.dot(x, x))
    if energy <= 0:
        return None
    corr = np.correlate(x, x, mode="full")[len(x) - 1:]
    lo, hi = SAMPLE_RATE // 400, SAMPLE_RATE // 75
    lag = int(np.argmax(corr[lo:hi])) + lo
    if corr[lag] / energy < 0.3:  # not periodic enough: noise or a consonant
        return None
    return SAMPLE_RATE / lag


def voice_features(pcm: bytes, text: str) -> VoiceFeatures | None:
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    n = len(samples) // FRAME
    if n < 10:
        return None
    frames = samples[: n * FRAME].reshape(n, FRAME)
    rms = np.sqrt((frames ** 2).mean(axis=1))
    floor = float(np.percentile(rms, 20))
    voiced = rms > max(250.0, floor * 3.0)
    voiced_s = float(voiced.sum()) * FRAME / SAMPLE_RATE
    words = len(text.split())
    if voiced_s < 0.4 or not words:
        return None
    level = float(rms[voiced].mean())
    pitches = [p for p in (_pitch(f) for f in frames[voiced][:300]) if p]
    return VoiceFeatures(
        duration_s=round(len(samples) / SAMPLE_RATE, 2),
        voiced_s=round(voiced_s, 2),
        words=words,
        rate_wps=round(words / voiced_s, 2),
        loudness_db=round(20 * math.log10(max(level, 1.0) / 32768.0), 1),
        pitch_hz=round(float(np.median(pitches)), 1) if len(pitches) >= 5 else None,
    )
