"""Voice pipeline end to end with stand-ins for Whisper and Piper (deterministic, no models needed)."""

import io
import math
import time
import wave
from array import array

import pytest
from fastapi.testclient import TestClient

from conftest import FakeBrowser, FakeDesktop, FakeOllama, fake_stats, make_profile
from nova.config import Settings
from nova.main import create_app
from nova.voice.stt import Transcript
from nova.voice.tts import Speech


class FakeSTT:
    """Returns queued transcripts, one per detected utterance."""

    def __init__(self, downloaded=True):
        self.downloaded = downloaded
        self.queue: list[str] = []
        self.language = "ur"
        self.model_size = "small"
        self.loaded = True
        self.load_error = None
        self.calls = 0

    def model_downloaded(self):
        return self.downloaded

    def load(self):
        pass

    def transcribe(self, pcm, sample_rate=16000):
        self.calls += 1
        text = self.queue.pop(0) if self.queue else ""
        return Transcript(text=text, language="ur", duration_s=len(pcm) / 32000, latency_ms=5,
                          no_speech_prob=0.0, avg_logprob=-0.2)


class FakeTTS:
    def __init__(self, available=True):
        self.available = available
        self.voice = "ur_PK-fasih-medium"
        self.spoken: list[str] = []

    def is_available(self, voice=None):
        return self.available

    def available_voices(self):
        return [{"id": self.voice, "label": "Fasih"}] if self.available else []

    def load(self):
        pass

    def synthesize(self, text, voice=None):
        self.spoken.append(text)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(bytes(2205 * 2))
        return Speech(wav=buf.getvalue(), duration_s=0.1, latency_ms=1, spoken_text=text)


def utterance() -> bytes:
    """0.3 s silence + 1 s 'speech' + 1.2 s silence, as 16 kHz int16."""
    speech = array("h", (int(6000 * math.sin(2 * math.pi * 220 * i / 16000)) for i in range(16000))).tobytes()
    return bytes(9600) + speech + bytes(38400)


@pytest.fixture
def voice_app(tmp_path):
    stt, tts = FakeSTT(), FakeTTS()
    app = create_app(Settings(data_dir=tmp_path, discovery_on_startup=False), scanner=make_profile,
                     stats=fake_stats, ollama_transport=FakeOllama(models=[]).transport, stt=stt, tts=tts,
                     desktop=FakeDesktop(), browser_controller=FakeBrowser())
    with TestClient(app) as client:
        yield client, stt, tts


def stream(ws, audio: bytes, chunk: int = 3200):
    for i in range(0, len(audio), chunk):
        ws.send_bytes(audio[i:i + chunk])


def receive_until(ws, kind: str, limit: int = 20):
    seen = []
    for _ in range(limit):
        msg = ws.receive_json()
        seen.append(msg["type"])
        if msg["type"] == kind:
            return seen
    raise AssertionError(f"no {kind}: {seen}")


def events(client, kind):
    return [e for e in client.app.state.bus.history() if e.type.value == kind]


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


def test_push_to_talk_runs_command_and_speaks_reply(voice_app):
    client, stt, tts = voice_app
    stt.queue = ["ہی نووا، میرا سسٹم چیک کرو۔"]
    with client.websocket_connect("/ws/voice") as ws:
        ws.send_json({"type": "start", "mode": "ptt"})
        stream(ws, utterance())
        seen = receive_until(ws, "done")
    assert seen[:3] == ["speech_start", "processing", "heard"]
    convo = client.get("/api/conversations").json()[0]
    assert convo["source"] == "voice" and convo["user_text"] == "میرا سسٹم چیک کرو۔"  # wake word stripped
    assert convo["intent"] == "system_info"
    wait_for(lambda: events(client, "NOVA_SPEAK"))
    speech_id = events(client, "NOVA_SPEAK")[0].data["speech_id"]
    r = client.get(f"/api/voice/speech/{speech_id}")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content[:4] == b"RIFF"
    assert tts.spoken and "Test CPU 9000" in tts.spoken[0]
    assert client.get("/api/status").json()["state"] == "IDLE"  # mic closed after one utterance


def test_continuous_ignores_speech_without_wake_word(voice_app):
    client, stt, _ = voice_app
    stt.queue = ["آج موسم بہت اچھا ہے۔"]
    with client.websocket_connect("/ws/voice") as ws:
        ws.send_json({"type": "start", "mode": "continuous"})
        stream(ws, utterance())
        receive_until(ws, "processing")
        wait_for(lambda: stt.calls == 1 and client.app.state.orchestrator.state.value == "LISTENING")
    # Privacy: nothing about the overheard sentence is shown or stored.
    assert client.get("/api/conversations").json() == []
    assert not events(client, "VOICE_TRANSCRIBED")
    assert all("موسم" not in (e.message or "") for e in client.app.state.bus.history())


def test_continuous_with_wake_word_runs_command(voice_app):
    client, stt, _ = voice_app
    stt.queue = ["Hey NOVA, RAM check karo"]
    with client.websocket_connect("/ws/voice") as ws:
        ws.send_json({"type": "start", "mode": "continuous"})
        stream(ws, utterance())
        receive_until(ws, "heard")
        wait_for(lambda: client.get("/api/conversations").json())
    assert client.get("/api/conversations").json()[0]["user_text"] == "RAM check karo"
    assert events(client, "WAKE_WORD_DETECTED")


def test_wake_word_alone_then_follow_up_without_wake_word(voice_app):
    client, stt, tts = voice_app
    stt.queue = ["ہے نووا", "storage check karo"]
    with client.websocket_connect("/ws/voice") as ws:
        ws.send_json({"type": "start", "mode": "continuous"})
        stream(ws, utterance())
        wait_for(lambda: tts.spoken)
        assert tts.spoken[0] == "Ji, farmaiye?"
        client.app.state.voice._muted_until = 0  # skip waiting for the reply to finish playing
        stream(ws, utterance())
        receive_until(ws, "heard")
        wait_for(lambda: client.get("/api/conversations").json())
    assert client.get("/api/conversations").json()[0]["user_text"] == "storage check karo"


def test_audio_ignored_while_nova_is_speaking(voice_app):
    client, stt, _ = voice_app
    stt.queue = ["Hey NOVA, RAM check karo"]
    client.app.state.voice.set_playback(True)
    with client.websocket_connect("/ws/voice") as ws:
        ws.send_json({"type": "start", "mode": "continuous"})
        stream(ws, utterance())
        ws.send_json({"type": "stop"})
    assert stt.calls == 0


def test_missing_model_reports_error(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, discovery_on_startup=False), scanner=make_profile,
                     stats=fake_stats, ollama_transport=FakeOllama(models=[]).transport,
                     stt=FakeSTT(downloaded=False), tts=FakeTTS(available=False), desktop=FakeDesktop(), browser_controller=FakeBrowser())
    with TestClient(app) as client:
        with client.websocket_connect("/ws/voice") as ws:
            ws.send_json({"type": "start", "mode": "ptt"})
            msg = ws.receive_json()
        assert msg["type"] == "error" and "download" in msg["message"]
        status = client.get("/api/voice/status").json()
        assert status["stt"]["downloaded"] is False and status["tts"]["available"] is False
        assert client.get("/api/status").json()["capabilities"]["voice"] is False
        assert client.post("/api/voice/speak", json={"text": "salam"}).status_code == 409


def test_speak_modes(voice_app):
    client, _, tts = voice_app
    client.post("/api/command", json={"text": "RAM check karo"})  # text command, default voice_only
    time.sleep(0.2)
    assert tts.spoken == []
    client.put("/api/settings", json={"speak_responses": "always"})
    client.post("/api/command", json={"text": "RAM check karo"})
    wait_for(lambda: tts.spoken)
    assert "RAM" in tts.spoken[0]


def test_speak_endpoint_and_voice_status(voice_app):
    client, _, tts = voice_app
    r = client.post("/api/voice/speak", json={"text": "Assalam-o-Alaikum"})
    assert r.status_code == 200 and client.get(f"/api/voice/speech/{r.json()['speech_id']}").status_code == 200
    assert client.get("/api/voice/speech/doesnotexist").status_code == 404
    s = client.get("/api/voice/status").json()
    assert s["stt"]["downloaded"] and s["tts"]["available"] and s["speak_responses"] == "voice_only"


def test_voice_settings_validation(voice_app):
    client, _, _ = voice_app
    assert client.put("/api/settings", json={"stt_language": "fr"}).status_code == 422
    assert client.put("/api/settings", json={"tts_voice": "../../evil"}).status_code == 422
    assert client.put("/api/settings", json={"speak_responses": "sometimes"}).status_code == 422
    assert client.put("/api/settings", json={"stt_language": "hi"}).status_code == 200
    assert client.app.state.voice.stt.language == "hi"
