"""Speech-to-text through OpenAI first (fast, Phase 13C), local Whisper as the fallback.

Admin's choice: with OpenAI on, every utterance the microphone picks up is sent to OpenAI for transcription -
including, in continuous listening, speech that turns out not to start with the wake word (it is then dropped here
and never shown or stored by NOVA; OpenAI's own data policy applies). No internet, a wrong key or no credit: the
local Whisper model answers instead, so voice keeps working offline.
"""

from __future__ import annotations

import io
import logging
import time
import wave
from typing import Callable

import httpx

from ..ai.openai_provider import OPENAI_URL, OpenAIError, explain, raise_for
from .stt import INITIAL_PROMPTS, SpeechToText, Transcript

log = logging.getLogger("nova.voice.stt")

DEFAULT_STT_MODEL = "gpt-4o-mini-transcribe"
TIMEOUT_S = 12.0


def wav_bytes(pcm16: bytes, sample_rate: int = 16_000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm16)
    return buf.getvalue()


class CloudFirstSTT:
    """Same interface as SpeechToText (the voice service does not care where the text comes from)."""

    def __init__(self, local: SpeechToText, key: Callable[[], str | None], engine: Callable[[], str],
                 model: Callable[[], str] | None = None, base_url: str = OPENAI_URL,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.local = local
        self._key = key
        self._engine = engine  # "auto" | "openai" | "local"
        self._model = model or (lambda: DEFAULT_STT_MODEL)
        self.base_url = base_url
        self._transport = transport
        self.cloud_error: str | None = None

    # -- the local model's interface, passed through
    @property
    def model_size(self) -> str:
        return self.local.model_size

    @property
    def language(self) -> str:
        return self.local.language

    @language.setter
    def language(self, value: str) -> None:
        self.local.language = value

    @property
    def loaded(self) -> bool:
        return self.local.loaded

    @property
    def load_error(self) -> str | None:
        return self.local.load_error

    def load(self) -> None:
        self.local.load()

    def warm_up(self) -> None:
        self.local.warm_up()

    def model_downloaded(self) -> bool:
        """Voice works when either engine can answer."""
        return self.use_cloud or self.local.model_downloaded()

    # -- which engine
    @property
    def use_cloud(self) -> bool:
        engine = self._engine()
        return bool(self._key()) and engine in ("auto", "openai")

    @property
    def engine(self) -> str:
        return "openai" if self.use_cloud else "local"

    @property
    def cloud_model(self) -> str:
        return self._model()

    def transcribe(self, pcm16: bytes, sample_rate: int = 16_000) -> Transcript:
        if self.use_cloud:
            try:
                result = self._cloud(pcm16, sample_rate)
                self.cloud_error = None
                return result
            except (httpx.HTTPError, OpenAIError, ValueError, KeyError) as exc:
                self.cloud_error = explain(exc)
                log.warning("OpenAI transcription failed, using local Whisper: %s", self.cloud_error)
        return self.local.transcribe(pcm16, sample_rate)

    def _cloud(self, pcm16: bytes, sample_rate: int) -> Transcript:
        language = None if self.local.language == "auto" else self.local.language
        data = {"model": self.cloud_model, "response_format": "json"}
        if language:
            data["language"] = language
        prompt = INITIAL_PROMPTS.get(language or "ur")
        if prompt:
            data["prompt"] = prompt
        started = time.perf_counter()
        with httpx.Client(base_url=self.base_url, timeout=TIMEOUT_S, transport=self._transport,
                          headers={"Authorization": f"Bearer {self._key() or ''}"}) as client:
            r = client.post("/audio/transcriptions", data=data,
                            files={"file": ("speech.wav", wav_bytes(pcm16, sample_rate), "audio/wav")})
        raise_for(r)
        text = str(r.json().get("text") or "").strip()
        return Transcript(text=text, language=language, duration_s=len(pcm16) / 2 / sample_rate,
                          latency_ms=int((time.perf_counter() - started) * 1000), no_speech_prob=0.0,
                          avg_logprob=0.0, provider="openai")
