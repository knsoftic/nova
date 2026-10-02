"""Text-to-speech with Piper's offline Urdu voices (data/models/piper/*.onnx)."""

from __future__ import annotations

import io
import json
import logging
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .translit import prepare_for_speech

log = logging.getLogger("nova.voice.tts")

VOICE_LABELS = {
    "ur_PK-fasih-medium": "Fasih (mard, Urdu)",
    "ur_PK-aegis_female-medium": "Aegis (khatoon, Urdu)",
}
# Long replies (e.g. the full system report) are cut to ~20 s of speech; the full text stays on screen.
MAX_SPEECH_CHARS = 220
REST_ON_SCREEN = " باقی تفصیل سکرین پر ہے۔"  # "Baqi tafseel screen par hai."


def shorten_for_speech(spoken: str, limit: int = MAX_SPEECH_CHARS) -> str:
    if len(spoken) <= limit:
        return spoken
    # Cut at the last sentence end that fits; fall back to a word boundary.
    cut = max(spoken.rfind(mark, 0, limit) for mark in ("۔", ".", "!", "?", "؟"))
    if cut < limit // 3:
        cut = spoken.rfind(" ", 0, limit)
    return spoken[: cut + 1].rstrip() + REST_ON_SCREEN


@dataclass
class Speech:
    wav: bytes
    duration_s: float
    latency_ms: int
    spoken_text: str


class TextToSpeech:
    def __init__(self, voices_dir: Path, voice: str = "ur_PK-fasih-medium") -> None:
        self.voices_dir = voices_dir
        self.voice = voice
        self._loaded: dict[str, Any] = {}
        self._lock = threading.Lock()

    def available_voices(self) -> list[dict[str, str]]:
        voices = []
        for onnx in sorted(self.voices_dir.glob("*.onnx")):
            if onnx.with_suffix(".onnx.json").exists():
                voices.append({"id": onnx.stem, "label": VOICE_LABELS.get(onnx.stem, onnx.stem)})
        return voices

    def is_available(self, voice: str | None = None) -> bool:
        return (self.voices_dir / f"{voice or self.voice}.onnx").exists()

    def _get(self, voice: str) -> Any:
        if voice not in self._loaded:
            from piper import PiperVoice

            path = self.voices_dir / f"{voice}.onnx"
            if not path.exists():
                raise FileNotFoundError(f"Voice '{voice}' download nahi hui")
            started = time.perf_counter()
            self._loaded[voice] = PiperVoice.load(str(path))
            log.info("Piper voice %s loaded in %.1fs", voice, time.perf_counter() - started)
        return self._loaded[voice]

    def load(self) -> None:
        with self._lock:
            self._get(self.voice)

    def synthesize(self, text: str, voice: str | None = None) -> Speech:
        spoken = shorten_for_speech(prepare_for_speech(text))
        started = time.perf_counter()
        with self._lock:
            piper_voice = self._get(voice or self.voice)
            config = json.loads((self.voices_dir / f"{voice or self.voice}.onnx.json").read_text(encoding="utf-8"))
            rate = int(config["audio"]["sample_rate"])
            pcm = b"".join(chunk.audio_int16_bytes for chunk in piper_voice.synthesize(spoken))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm)
        return Speech(wav=buf.getvalue(), duration_s=len(pcm) / 2 / rate,
                      latency_ms=int((time.perf_counter() - started) * 1000), spoken_text=spoken)
