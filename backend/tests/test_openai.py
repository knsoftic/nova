"""Phase 13C: OpenAI as an optional brain and speech-to-text, with the local models as the fallback.

Tests never talk to OpenAI: a fake API answers. The key is a dummy and must never show up anywhere.
"""

import json

import httpx

from conftest import FakeOllama, build_client
from nova.voice.openai_stt import CloudFirstSTT
from nova.voice.stt import Transcript

KEY = "sk-test-dummy-1234567890"


class FakeOpenAI:
    def __init__(self):
        self.status = 200
        self.requests: list[httpx.Request] = []
        self.answer = {"intents": [{"name": "chat"}],
                       "answer": "Coffee mein caffeine zyada hoti hai, chai mein kam."}
        self.transcript = "ہے نووا، کروم کھولو"

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "nope"}})
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4o-mini-transcribe"}]})
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(self.answer)}}]})
        if request.url.path.endswith("/audio/transcriptions"):
            return httpx.Response(200, json={"text": self.transcript})
        return httpx.Response(404)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def cmd(client, text):
    return client.post("/api/command", json={"text": text}).json()


def test_openai_brain_with_a_saved_key_and_the_local_fallback(tmp_path):
    cloud = FakeOpenAI()
    with build_client(tmp_path, openai_transport=cloud.transport) as c:
        question = "chai aur coffee mein kya farq hai"
        assert c.get("/api/ai/status").json()["llm_provider"] == "ollama"
        assert c.get("/api/openai/status").json()["configured"] is False
        assert cmd(c, question)["fallback_reason"] == "model_unavailable" and not cloud.requests  # no key: no cloud

        assert c.put("/api/secrets/openai_api_key", json={"value": KEY}).status_code == 200
        status = c.get("/api/ai/status").json()
        assert status["llm_provider"] == "openai" and status["model"] == "gpt-4o-mini" and status["model_ready"]
        reply = cmd(c, question)
        assert reply["provider"] == "openai:gpt-4o-mini" and "caffeine" in reply["response"]
        sent = cloud.requests[-1]
        assert sent.headers["authorization"] == f"Bearer {KEY}"
        assert json.loads(sent.content)["response_format"] == {"type": "json_object"}
        assert cmd(c, "RAM batao")["provider"] == "rule_based"  # clear commands stay instant and local (hybrid)

        status = c.get("/api/openai/status").json()
        assert status["key_masked"] == "••••7890" and status["llm_active"] == "openai"
        assert c.post("/api/openai/test").json() == {"ok": True, "message": "Key theek"}

        cloud.status = 401  # wrong/expired key: NOVA keeps working (rules here; no local model)
        reply = cmd(c, question)
        assert reply["status"] != "failed" and reply["fallback_reason"] == "http_error"
        assert c.get("/api/openai/status").json()["llm_error"] == "OpenAI API key ghalat ya band hai"
        assert c.post("/api/openai/test").json()["ok"] is False

        c.put("/api/settings", json={"llm_provider": "ollama"})  # the user can keep the brain local
        assert c.get("/api/ai/status").json()["llm_provider"] == "ollama"

        # The key never appears in replies, the activity log or events.
        everything = json.dumps(c.get("/api/activity?limit=200").json()) + json.dumps(
            [e.model_dump(mode="json") for e in c.app.state.bus.history()]) + json.dumps(c.get("/api/settings").json())
        assert KEY not in everything
        c.delete("/api/secrets/openai_api_key")
        assert c.get("/api/openai/status").json()["configured"] is False


def test_openai_failure_falls_back_to_the_local_model(tmp_path):
    cloud, ollama = FakeOpenAI(), FakeOllama(models=["qwen3:4b"])
    ollama.reply = lambda text: {"intents": [{"name": "chat"}], "answer": "Local jawab."}
    with build_client(tmp_path, ollama, openai_transport=cloud.transport) as c:
        c.put("/api/secrets/openai_api_key", json={"value": KEY})
        cloud.status = 500
        reply = cmd(c, "chai aur coffee mein kya farq hai")
        assert reply["provider"] == "ollama:qwen3:4b" and "Local jawab" in reply["response"]
        assert "500" in c.get("/api/openai/status").json()["llm_error"]


class LocalSTT:
    def __init__(self, downloaded=True):
        self.downloaded, self.language, self.model_size = downloaded, "ur", "small"
        self.loaded, self.load_error, self.calls = True, None, 0

    def model_downloaded(self):
        return self.downloaded

    def load(self):
        pass

    def transcribe(self, pcm, sample_rate=16000):
        self.calls += 1
        return Transcript(text="local", language="ur", duration_s=1.0, latency_ms=3000, no_speech_prob=0.0,
                          avg_logprob=-0.2)


def test_speech_goes_to_openai_with_a_key_and_falls_back_to_local_whisper():
    cloud, local = FakeOpenAI(), LocalSTT(downloaded=False)
    key, engine = {"value": None}, {"value": "auto"}
    stt = CloudFirstSTT(local, key=lambda: key["value"], engine=lambda: engine["value"],
                        transport=httpx.MockTransport(cloud.handler))
    pcm = bytes(32000)
    assert stt.engine == "local" and not stt.model_downloaded()  # no key, no local model: voice cannot work
    assert stt.transcribe(pcm).text == "local" and not cloud.requests

    key["value"] = KEY
    assert stt.engine == "openai" and stt.model_downloaded()  # the cloud alone is enough
    t = stt.transcribe(pcm)
    assert t.provider == "openai" and t.text == "ہے نووا، کروم کھولو" and local.calls == 1
    sent = cloud.requests[-1]
    body = sent.content
    assert sent.headers["authorization"] == f"Bearer {KEY}" and b"gpt-4o-mini-transcribe" in body
    assert b'name="language"' in body and b"RIFF" in body  # Urdu, as a WAV file

    cloud.status = 429  # no credit: local Whisper answers, the reason is kept for the status
    assert stt.transcribe(pcm).text == "local" and "429" in stt.cloud_error
    engine["value"] = "local"  # the user can keep voice on the PC
    cloud.status = 200
    assert stt.engine == "local" and stt.transcribe(pcm).text == "local"


def test_openai_self_test(tmp_path):
    cloud = FakeOpenAI()
    with build_client(tmp_path, openai_transport=cloud.transport) as c:
        result = c.post("/api/admin/selftest", json={"scope": "13C"}).json()["results"][0]
        assert result["status"] == "info"
        c.put("/api/secrets/openai_api_key", json={"value": KEY})
        result = c.post("/api/admin/selftest", json={"scope": "13C"}).json()["results"][0]
        assert result["status"] == "pass" and "brain openai" in result["detail"]
        cloud.status = 401
        result = c.post("/api/admin/selftest", json={"scope": "13C"}).json()["results"][0]
        assert result["status"] == "fail" and "local" in result["detail"]
