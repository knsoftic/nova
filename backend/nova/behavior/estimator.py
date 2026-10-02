"""Estimates the user's communication state from words, conversation context and (for voice) how they spoke.

It is an estimate, never a fact: weak or single signals stay "neutral", the label is hedged ("shayad ..."), and the
reasons are shown. Everything here lives in RAM for the current session; nothing is written to disk.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .signals import LABELS, Signal, VoiceFeatures, is_simple_command, text_signals

REPORT_AT = 0.45  # weaker evidence is not reported (state stays neutral)
SURE_AT = 0.75  # below this the label says "shayad"
VOICE_CAP = 0.6  # voice alone never makes NOVA "sure"
CARRY_S = 180.0  # an earlier estimate still counts a little for this long
BASELINE_AFTER = 3  # utterances needed before voice is compared with the user's own normal


@dataclass
class Estimate:
    state: str = "neutral"
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    simple: bool = False  # a short plain command: do it, do not explain

    @property
    def label(self) -> str:
        if self.state == "neutral":
            return ""
        word = LABELS[self.state]
        return f"{word} lagte hain" if self.confidence >= SURE_AT else f"shayad {word}"

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state, "confidence": round(self.confidence, 2), "label": self.label,
                "reasons": self.reasons}


@dataclass
class Turn:
    """What the estimator needs from the short-term memory."""

    user: str
    outcome: str  # done | failed | denied | answered | not_understood
    at: float


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


class BehaviorEstimator:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.baseline: dict[str, float] = {}
        self.voice_samples = 0
        self.last: Estimate = Estimate()
        self.last_at = 0.0

    def reset(self) -> None:
        self.baseline.clear()
        self.voice_samples = 0
        self.forget_mood()

    def forget_mood(self) -> None:
        """A new conversation starts without the earlier estimate (the voice baseline stays)."""
        self.last, self.last_at = Estimate(), 0.0

    def _voice(self, v: VoiceFeatures) -> list[Signal]:
        out: list[Signal] = []
        b = self.baseline
        if self.voice_samples >= BASELINE_AFTER:
            if v.rate_wps >= b["rate"] * 1.3:  # alone this is enough for a hedged "shayad jaldi mein"
                out.append(Signal("hurried", 0.45, "aam se tez bole"))
            if v.loudness_db >= b["loud"] + 6:
                out += [Signal("frustrated", 0.2, "aam se zor se bole"), Signal("hurried", 0.1, "aam se zor se bole")]
            if v.pitch_hz and b.get("pitch") and v.pitch_hz >= b["pitch"] * 1.2:
                out.append(Signal("frustrated", 0.15, "awaaz aam se oonchi"))
            if v.rate_wps <= b["rate"] * 0.7 and v.loudness_db <= b["loud"] - 5:
                out.append(Signal("tired", 0.35, "aam se dheere aur halki awaaz"))
        elif v.rate_wps >= 4.2:  # no baseline yet: only a clearly fast pace counts
            out.append(Signal("hurried", 0.3, "bohat tez bole"))
        # Learn this user's normal (slowly, so one excited sentence does not move it much).
        for key, value in (("rate", v.rate_wps), ("loud", v.loudness_db), ("pitch", v.pitch_hz)):
            if value is None:
                continue
            b[key] = value if key not in b else 0.7 * b[key] + 0.3 * value
        self.voice_samples += 1
        return out

    def _context(self, text: str, turns: list[Turn], now: float) -> list[Signal]:
        out: list[Signal] = []
        if not turns:
            return out
        key = _norm(text)
        recent = [t for t in turns if now - t.at <= 120]
        # Saying the same thing again after it did not work (repeating a command that worked is normal).
        if key and any(_norm(t.user) == key and t.outcome != "done" for t in recent[-2:]):
            out.append(Signal("frustrated", 0.45, "wahi baat dobara kahi"))
        last = turns[-1]
        if last.outcome in ("failed", "not_understood"):
            out.append(Signal("frustrated", 0.25, "pichla jawab kaam ka nahi tha"))
            if last.outcome == "not_understood":
                out.append(Signal("confused", 0.2, "pichli baat samajh nahi aayi thi"))
        if sum(t.outcome in ("failed", "not_understood") for t in turns[-3:]) >= 2:
            out.append(Signal("frustrated", 0.35, "kai kaam nahi hue"))
        if now - last.at < 4.0 and len(text.split()) <= 6:
            out.append(Signal("hurried", 0.2, "foran agli command"))
        return out

    def estimate(self, text: str, turns: list[Turn], voice: VoiceFeatures | None = None) -> Estimate:
        now = self.clock()
        signals = text_signals(text) + self._context(text, turns, now)
        voice_signals = self._voice(voice) if voice is not None else []
        scores: dict[str, float] = {}
        reasons: dict[str, list[str]] = {}
        for s in signals + voice_signals:
            scores[s.state] = scores.get(s.state, 0.0) + s.weight
            if s.reason not in reasons.setdefault(s.state, []):
                reasons[s.state].append(s.reason)
        # A recent estimate fades but still counts a little (frustration does not vanish in one sentence).
        if self.last.state != "neutral" and now - self.last_at <= CARRY_S:
            scores[self.last.state] = scores.get(self.last.state, 0.0) + self.last.confidence * 0.4
            reasons.setdefault(self.last.state, []).append("pichli baat se")
        if scores.get("positive", 0) >= 0.5:  # thanks/praise outweighs earlier irritation
            scores["frustrated"] = scores.get("frustrated", 0.0) * 0.3
        result = Estimate(simple=is_simple_command(text))
        if scores:
            state, score = max(scores.items(), key=lambda kv: kv[1])
            only_voice = not any(s.state == state for s in signals)
            score = min(score, VOICE_CAP if only_voice else 0.95)
            if score >= REPORT_AT:
                result.state, result.confidence, result.reasons = state, score, reasons[state][:4]
        self.last, self.last_at = result, now
        return result
