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
from collections import OrderedDict, deque
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal

from ..behavior.signals import voice_features
from ..events import EventBus, EventType, NovaEvent, NovaState
from .segmenter import Segmenter
from .stt import SpeechToText
from .tts import TextToSpeech
from .wake import detect_wake

if TYPE_CHECKING:
    from ..orchestrator import Orchestrator
    from ..permissions import PermissionEngine
    from ..user_settings import UserSettings

log = logging.getLogger("nova.voice")

VOICE = "Voice"
FOLLOW_UP_SECONDS = 8.0  # after "Hey NOVA" alone, the next utterance needs no wake word
# After a voice command (and NOVA's spoken reply), the next command needs no wake word for this long - a conversation.
CONVERSATION_SECONDS = 15.0
MAX_QUEUED = 3  # utterances waiting while the previous one is being understood (oldest dropped beyond this)
# Whisper hears cut-off speech badly (e.g. "Hey NOVA" at the very start): a little silence on both sides helps.
PAD = bytes(int(16_000 * 0.3) * 2)
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
        self.busy = False  # transcribing / handling an utterance; new speech is queued, never dropped
        self.follow_up_until = 0.0
        self.conversation_from = 0.0  # when the last voice command was handled (0 = no conversation going on)
        self._queue: deque[tuple[bytes, float]] = deque(maxlen=MAX_QUEUED)  # (audio, when it was spoken)
        self._worker: asyncio.Task[Any] | None = None
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
        self._queue.clear()
        await self.service.orchestrator.set_voice_active(False)

    async def feed(self, pcm: bytes) -> None:
        if not self.active:
            return
        if self.service.muted:  # NOVA is speaking: never hear itself (and start clean afterwards)
            self.segmenter.reset()
            return
        for kind, payload in self.segmenter.feed(pcm):
            if kind == "start":
                await self.send({"type": "speech_start"})
            elif kind == "segment":
                if self.mode == "ptt" and (self.busy or self._queue):
                    continue  # push-to-talk: one utterance per press
                self._queue.append((payload, time.monotonic()))
                if self._worker is None or self._worker.done():
                    self._worker = asyncio.create_task(self._drain())
                    self._tasks.add(self._worker)
                    self._worker.add_done_callback(self._tasks.discard)

    async def _drain(self) -> None:
        """Utterances are understood one after another; speech while NOVA is busy waits instead of being lost."""
        while self._queue and self.active:
            pcm, spoken_at = self._queue.popleft()
            self.busy = True
            try:
                await self._handle_segment(pcm, spoken_at)
            finally:
                self.busy = False

    async def _handle_segment(self, pcm: bytes, spoken_at: float | None = None) -> None:
        svc = self.service
        orch = svc.orchestrator
        spoken_at = spoken_at or time.monotonic()
        try:
            await self.send({"type": "processing"})
            await orch.set_state(NovaState.THINKING)
            transcript = await asyncio.to_thread(svc.stt.transcribe, PAD + pcm + PAD)
            settings = svc.settings()
            # Answering NOVA's own question ("haan"/"nahi"), or talking on right after a command, needs no wake word.
            in_follow_up = (spoken_at < self.follow_up_until or self._in_conversation(spoken_at)
                            or bool(svc.permissions and svc.permissions.pending))

            if not transcript.usable:
                await self._finish(heard=False)
                return

            command = transcript.text
            if self.mode == "continuous" and not in_follow_up:
                wake = detect_wake(transcript.text, settings.assistant_name, settings.wake_word)
                if not wake.detected:
                    # Not addressed to NOVA: dropped - nothing is shown or stored; the UI only hears "ignored".
                    await self.send({"type": "ignored"})
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
                                "audio_s": round(transcript.duration_s, 1), "stt_ms": transcript.latency_ms,
                                "stt": transcript.provider})
            )
            await self.send({"type": "heard", "text": command})
            # How it was said (speed, loudness, pitch): measured here, used once for the estimate, never stored.
            voice = None
            if settings.emotion_awareness and settings.voice_signals:
                voice = await asyncio.to_thread(voice_features, pcm, command)
            await orch.handle_command(command, source="voice", voice=voice)
            if self.mode == "continuous":  # a conversation: the next command needs no "Hey NOVA" for a while
                self.conversation_from = time.monotonic()
                await self.send({"type": "follow_up", "seconds": CONVERSATION_SECONDS})
            await self._finish(heard=True)
        except Exception as exc:  # never let one bad utterance kill the session
            log.exception("Voice segment failed")
            await svc.bus.publish(NovaEvent(type=EventType.TASK_FAILED, agent=VOICE,
                                            message="Awaaz samajhne mein masla aa gaya", data={"error": type(exc).__name__}))
            await self._finish(heard=False)

    def _in_conversation(self, spoken_at: float) -> bool:
        """The conversation window counts from when NOVA finished speaking its reply (a long reply must not eat it)."""
        if not self.conversation_from:
            return False
        return spoken_at < max(self.conversation_from, self.service.speaking_until) + CONVERSATION_SECONDS

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
        permissions: PermissionEngine | None = None,
    ) -> None:
        self.permissions = permissions
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
        cloud = getattr(self.stt, "use_cloud", False)
        return {
            "stt": {"model": self.stt.cloud_model if cloud else self.stt.model_size, "language": self.stt.language,
                    "engine": "openai" if cloud else "local", "local_model": self.stt.model_size,
                    "downloaded": self.stt.model_downloaded(), "loaded": self.stt.loaded,
                    "error": self.stt.load_error, "cloud_error": getattr(self.stt, "cloud_error", None)},
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
        if getattr(self.stt, "use_cloud", False):
            parts.append(f"awaaz pehchanna OpenAI se ({self.stt.cloud_model})")
        local = getattr(self.stt, "local", self.stt)  # the local model is the fallback either way
        if local.model_downloaded():
            try:
                await asyncio.to_thread(getattr(local, "warm_up", local.load))
                parts.append(f"awaaz pehchanna tayyar (whisper {local.model_size})")
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
    def speaking_until(self) -> float:
        """When NOVA's current/last spoken reply ends (monotonic clock)."""
        return self._muted_until

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
                if event.type not in (EventType.NOVA_RESPONSE, EventType.PERMISSION_REQUIRED) or not event.message:
                    continue
                mode = self.settings().speak_responses
                source = event.data.get("source", "text")
                if mode == "always" or (mode == "voice_only" and source == "voice"):
                    try:
                        # The behavior layer may give a shorter spoken version (hurry, short replies).
                        await self.speak(event.data.get("speech") or event.message, event.task_id)
                    except Exception:
                        log.exception("Speech synthesis failed")
        finally:
            self.bus.unsubscribe(queue)
