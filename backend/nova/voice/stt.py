"""Speech-to-text with faster-whisper, fully offline (model files in data/models/whisper)."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("nova.voice.stt")

# Biases Whisper towards NOVA's vocabulary and the Urdu-script spelling of the name.
INITIAL_PROMPTS = {
    "ur": "ہے نووا، کروم کھولو۔ سسٹم چیک کرو۔ رام کتنی ہے؟",
    "hi": "हे नोवा, क्रोम खोलो। सिस्टम चेक करो।",
    "en": "Hey NOVA, open Chrome. Check the system.",
}

# Phrases Whisper is known to invent on silence or noise.
HALLUCINATIONS = {
    "شکریہ", "شکریہ۔", "thank you.", "thank you", "thanks for watching!", "thanks for watching.", "you",
    "سبسکرائب کریں", "धन्यवाद", "धन्यवाद।", "...", ".",
}


@dataclass
class Transcript:
    text: str
    language: str | None
    duration_s: float
    latency_ms: int
    no_speech_prob: float
    avg_logprob: float

    @property
    def usable(self) -> bool:
        if not self.text or self.text.strip().lower() in HALLUCINATIONS:
            return False
        return not (self.no_speech_prob > 0.6 and self.avg_logprob < -1.0)


class SpeechToText:
    def __init__(self, models_dir: Path, model_size: str = "small", language: str = "ur") -> None:
        self.models_dir = models_dir
        self.model_size = model_size
        self.language = language  # ur | hi | en | auto
        self._model: Any = None
        self._lock = threading.Lock()
        self.load_error: str | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def model_downloaded(self) -> bool:
        repo = self.models_dir / f"models--Systran--faster-whisper-{self.model_size}"
        return any(repo.glob("snapshots/*/model.bin"))

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            from faster_whisper import WhisperModel

            if not self.model_downloaded():
                self.load_error = f"Whisper model '{self.model_size}' download nahi hua"
                raise FileNotFoundError(self.load_error)
            started = time.perf_counter()
            # local_files_only: never download at runtime; downloads need the user's permission.
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8",
                                       cpu_threads=min(8, os.cpu_count() or 4),
                                       download_root=str(self.models_dir), local_files_only=True)
            self.load_error = None
            log.info("Whisper %s loaded in %.1fs", self.model_size, time.perf_counter() - started)

    def transcribe(self, pcm16: bytes, sample_rate: int = 16_000) -> Transcript:
        self.load()
        audio = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        language = None if self.language == "auto" else self.language
        started = time.perf_counter()
        with self._lock:
            segments, info = self._model.transcribe(
                audio,
                language=language,
                beam_size=1,
                vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt=INITIAL_PROMPTS.get(language or "ur"),
                without_timestamps=True,
            )
            segments = list(segments)
        text = " ".join(s.text.strip() for s in segments).strip()
        return Transcript(
            text=text,
            language=info.language,
            duration_s=len(audio) / sample_rate,
            latency_ms=int((time.perf_counter() - started) * 1000),
            no_speech_prob=max((s.no_speech_prob for s in segments), default=1.0),
            avg_logprob=min((s.avg_logprob for s in segments), default=-10.0),
        )
