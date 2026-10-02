"""End-to-end voice check against a running backend, without a human speaker.

    .venv\\Scripts\\python.exe scripts\\voice_loopback.py

NOVA's own Urdu voice says each phrase; the audio is streamed to /ws/voice exactly like the app's
microphone (16 kHz int16, 100 ms chunks, real-time pace). Reports what NOVA heard, did and replied.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import time
import wave
from pathlib import Path

import httpx
import numpy as np
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nova.voice.tts import TextToSpeech  # noqa: E402

BASE = "http://127.0.0.1:8765"
VOICE_WS = "ws://127.0.0.1:8765/ws/voice"
EVENTS_WS = "ws://127.0.0.1:8765/ws"
PHRASES = [
    ("ptt", "Hey NOVA, mera system check karo"),
    ("ptt", "RAM kitni free hai"),
    ("continuous", "aaj mausam bohat achha hai"),  # no wake word: must be ignored
    ("continuous", "Hey NOVA, Windows ka version batao"),
]


def to_16k(wav_bytes: bytes) -> bytes:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        rate = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)
    n = int(len(pcm) * 16000 / rate)
    return np.interp(np.linspace(0, len(pcm) - 1, n), np.arange(len(pcm)), pcm).astype(np.int16).tobytes()


async def run_phrase(tts: TextToSpeech, mode: str, phrase: str) -> None:
    audio = bytes(16000) + to_16k(tts.synthesize(phrase).wav) + bytes(48000)
    events: list[dict] = []
    async with websockets.connect(EVENTS_WS) as ev, websockets.connect(VOICE_WS) as mic:
        await ev.recv()  # HELLO
        await mic.send(json.dumps({"type": "start", "mode": mode}))
        started = time.perf_counter()
        for i in range(0, len(audio), 3200):  # 100 ms chunks at real-time pace
            await mic.send(audio[i:i + 3200])
            await asyncio.sleep(0.1)
        deadline = time.perf_counter() + 60
        while time.perf_counter() < deadline:
            try:
                e = json.loads(await asyncio.wait_for(ev.recv(), timeout=8 if mode == "continuous" else 60))
            except asyncio.TimeoutError:
                break
            events.append(e)
            if e["type"] in ("NOVA_SPEAK", "TASK_FAILED"):
                break
        await mic.send(json.dumps({"type": "stop"}))
        # The real UI plays the reply and then reports playback finished, which un-mutes the mic.
        await ev.send(json.dumps({"type": "playback", "active": False}))
    total = time.perf_counter() - started - len(audio) / 32000
    heard = next((e for e in events if e["type"] == "VOICE_TRANSCRIBED"), None)
    reply = next((e for e in events if e["type"] == "NOVA_RESPONSE"), None)
    speak = next((e for e in events if e["type"] == "NOVA_SPEAK"), None)
    print(f"\n[{mode}] said: {phrase!r}")
    if not heard:
        print("   heard: (nothing acted on)" + (" - correct, no wake word" if "Hey" not in phrase else " - MISSED"))
        return
    print(f"   heard: {heard['data']['text']!r}  (stt {heard['data']['stt_ms']} ms)")
    print(f"   reply: {reply['message'] if reply else None!r}")
    if speak:
        r = httpx.get(f"{BASE}/api/voice/speech/{speak['data']['speech_id']}")
        print(f"   spoke: {speak['data']['duration_s']}s of audio ({len(r.content) // 1024} KB wav, tts {speak['data']['tts_ms']} ms)")
    print(f"   time from end of speech to spoken reply ready: {total:.1f}s")


async def main() -> None:
    status = httpx.get(f"{BASE}/api/voice/status").json()
    print("voice status:", json.dumps(status, ensure_ascii=False))
    models = Path(__file__).resolve().parent.parent.parent / "data" / "models" / "piper"
    tts = TextToSpeech(models, "ur_PK-aegis_female-medium")  # a different voice than NOVA's, like a user
    for mode, phrase in PHRASES:
        await run_phrase(tts, mode, phrase)


if __name__ == "__main__":
    asyncio.run(main())
