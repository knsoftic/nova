"""Voice service: microphone stream -> utterances -> transcript -> (wake word) -> command -> spoken reply.

Privacy: audio is processed in memory and discarded. In continuous mode, speech that does not
start with the wake word is dropped without being shown, logged or stored.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal

from ..events import EventBus, EventType, NovaEvent, NovaState
from .segmenter import Segmenter
from .stt import SpeechToText
from .tts import TextToSpeech
from .wake import detect_wake

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator
    from ..user_settings import UserSettings

log = logging.getLogger("nova.voice")

VOICE = "Voice"
FOLLOW_UP_SECONDS = 8.0  # after "Hey NOVA" alone, the next utterance needs no wake word
SPEECH_CACHE = 20
WAKE_ONLY_REPLY = "Ji, farmaiye?"

ListenMode = Literal["ptt", "continuous"]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class VoiceSession:
    """One open microphone stream from the UI."""

    def __init__(self, service: VoiceService, send: Send) -> None:
        self.service = service
        self.send = send
        self.mode: ListenMode = "ptt"
        self.segmenter = Segmenter()
        self.active = False
        self.busy = False  # transcribing / handling a command: incoming audio is ignored
        self.follow_up_until = 0.0
        self._tasks: set[asyncio.Task[Any]] = set()

    async def start(self, mode: ListenMode) -> None:
        if not self.service.stt.model_downloaded():
            await self.send({"type": "error", "message": "Speech model download nahi hua. Settings mein voice status dekhein."})
            return
        self.mode = mode
        self.active = True
        self.segmenter.reset()
        await self.service.orchestrator.set_voice_active(True)

    async def stop(self) -> None:
        self.active = False
        self.segmenter.reset()
        await self.service.orchestrator.set_voice_active(False)

    async def feed(self, pcm: bytes) -> None:
        if not self.active or self.busy or self.service.muted:
            return
        for kind, payload in self.segmenter.feed(pcm):
            if kind == "start":
                await self.send({"type": "speech_start"})
            elif kind == "segment":
                self.busy = True
                task = asyncio.create_task(self._handle_segment(payload))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _handle_segment(self, pcm: bytes) -> None:
        svc = self.service
        orch = svc.orchestrator
        try:
            await self.send({"type": "processing"})
            await orch.set_state(NovaState.THINKING)
            transcript = await asyncio.to_thread(svc.stt.transcribe, pcm)
            settings = svc.settings()
            in_follow_up = time.monotonic() < self.follow_up_until

            if not transcript.usable:
                await self._finish(heard=False)
                return

            command = transcript.text
            if self.mode == "continuous" and not in_follow_up:
                wake = detect_wake(transcript.text, settings.assistant_name, settings.wake_word)
                if not wake.detected:
                    # Not addressed to NOVA: drop silently, nothing is shown or stored.
                    await self._finish(heard=False)
                    return
                command = wake.command
                await svc.bus.publish(NovaEvent(type=EventType.WAKE_WORD_DETECTED, agent=VOICE,
                                                message=f"Wake word suna ({settings.wake_word})"))
            else:
                # Push-to-talk (or follow-up): the wake word is optional, strip it if present.
                wake = detect_wake(transcript.text, settings.assistant_name, settings.wake_word)
                if wake.detected:
                    command = wake.command
            self.follow_up_until = 0.0

            if not command:
                self.follow_up_until = time.monotonic() + FOLLOW_UP_SECONDS
                await svc.reply(WAKE_ONLY_REPLY)
                await self._finish(heard=True, keep_listening=True)
                return

            await svc.bus.publish(
                NovaEvent(type=EventType.VOICE_TRANSCRIBED, agent=VOICE, message=f'Suna: "{command}"',
                          data={"text": command, "language": transcript.language,
                                "audio_s": round(transcript.duration_s, 1), "stt_ms": transcript.latency_ms})
            )
            await self.send({"type": "heard", "text": command})
            await orch.handle_command(command, source="voice")
            await self._finish(heard=True)
        except Exception as exc:  # never let one bad utterance kill the session
            log.exception("Voice segment failed")
            await svc.bus.publish(NovaEvent(type=EventType.TASK_FAILED, agent=VOICE,
                                            message="Awaaz samajhne mein masla aa gaya", data={"error": type(exc).__name__}))
            await self._finish(heard=False)
        finally:
            self.busy = False
            self.segmenter.reset()

    async def _finish(self, heard: bool, keep_listening: bool = False) -> None:
        orch = self.service.orchestrator
        if orch.state == NovaState.THINKING:
            await orch.set_state(orch.rest_state)
        if self.mode == "ptt" and not keep_listening:
            await self.send({"type": "done", "heard": heard})
            await self.stop()

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if self.active:
            await self.stop()


class VoiceService:
    def __init__(
        self,
        bus: EventBus,
        orchestrator: Orchestrator,
        stt: SpeechToText,
        tts: TextToSpeech,
        settings: Callable[[], UserSettings],
    ) -> None:
        self.bus = bus
        self.orchestrator = orchestrator
        self.stt = stt
        self.tts = tts
        self.settings = settings
        self._speech: OrderedDict[str, bytes] = OrderedDict()
        self._muted_until = 0.0
        self._listener: asyncio.Task[Any] | None = None

    # ------------------------------------------------------------------ status / lifecycle

    def status(self) -> dict[str, Any]:
        s = self.settings()
        return {
            "stt": {"model": self.stt.model_size, "language": self.stt.language,
                    "downloaded": self.stt.model_downloaded(), "loaded": self.stt.loaded,
                    "error": self.stt.load_error},
            "tts": {"voice": self.tts.voice, "available": self.tts.is_available(), "voices": self.tts.available_voices()},
            "speak_responses": s.speak_responses,
            "continuous_listening": s.continuous_listening,
            "wake_word": s.wake_word,
        }

    def apply_settings(self, s: UserSettings) -> None:
        self.stt.language = s.stt_language
        self.tts.voice = s.tts_voice

    async def prepare(self) -> None:
        """Load models in the background so the first voice command is not slow."""
        parts = []
        if self.stt.model_downloaded():
            try:
                await asyncio.to_thread(self.stt.load)
                parts.append(f"awaaz pehchanna tayyar (whisper {self.stt.model_size})")
            except Exception as exc:
                parts.append(f"whisper load nahi hua ({type(exc).__name__})")
        else:
            parts.append("whisper model download nahi hua")
        if self.tts.is_available():
            try:
                await asyncio.to_thread(self.tts.load)
                parts.append(f"Urdu awaaz tayyar ({self.tts.voice})")
            except Exception as exc:
                parts.append(f"awaaz load nahi hui ({type(exc).__name__})")
        else:
            parts.append("Urdu voice download nahi hui")
        await self.bus.publish(NovaEvent(type=EventType.VOICE_STATUS, agent=VOICE,
                                         message="Voice: " + ", ".join(parts), data=self.status()))

    def start_listener(self) -> None:
        self._listener = asyncio.create_task(self._speak_responses())

    async def shutdown(self) -> None:
        if self._listener:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener

    # ------------------------------------------------------------------ speaking

    @property
    def muted(self) -> bool:
        """True while NOVA's own voice is playing, so it does not hear itself."""
        return time.monotonic() < self._muted_until

    def set_playback(self, active: bool) -> None:
        # The UI reports playback; a generous timeout covers a lost "ended" message.
        self._muted_until = time.monotonic() + (30.0 if active else 0.3)

    def get_speech(self, speech_id: str) -> bytes | None:
        return self._speech.get(speech_id)

    async def speak(self, text: str, task_id: str | None = None) -> str | None:
        if not self.tts.is_available():
            return None
        speech = await asyncio.to_thread(self.tts.synthesize, text)
        speech_id = uuid.uuid4().hex[:12]
        self._speech[speech_id] = speech.wav
        while len(self._speech) > SPEECH_CACHE:
            self._speech.popitem(last=False)
        self._muted_until = time.monotonic() + speech.duration_s + 1.0
        await self.bus.publish(
            NovaEvent(type=EventType.NOVA_SPEAK, task_id=task_id, agent=VOICE,
                      message=f"Bol raha hai ({speech.duration_s:.1f}s)",
                      data={"speech_id": speech_id, "duration_s": round(speech.duration_s, 2),
                            "tts_ms": speech.latency_ms})
        )
        return speech_id

    async def reply(self, text: str) -> None:
        """A short voice-only reply that is not a command (e.g. after the bare wake word)."""
        await self.bus.publish(NovaEvent(type=EventType.NOVA_RESPONSE, agent=VOICE, message=text,
                                         data={"response": text, "source": "voice", "intent": "wake"}))

    async def _speak_responses(self) -> None:
        queue = self.bus.subscribe()
        try:
            while True:
                event = await queue.get()
                if event.type != EventType.NOVA_RESPONSE or not event.message:
                    continue
                mode = self.settings().speak_responses
                source = event.data.get("source", "text")
                if mode == "always" or (mode == "voice_only" and source == "voice"):
                    try:
                        await self.speak(event.message, event.task_id)
                    except Exception:
                        log.exception("Speech synthesis failed")
        finally:
            self.bus.unsubscribe(queue)
