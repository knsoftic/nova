"""Phase 3 backend support: user settings, configurable wake word, voice (mic) state."""

import asyncio

import pytest

from nova.ai.rule_based import RuleBasedProvider


def test_settings_defaults(client):
    s = client.get("/api/settings").json()
    assert s == {"assistant_name": "NOVA", "wake_word": "Hey NOVA", "continuous_listening": False,
                 "startup_mode": "active", "ai_mode": "hybrid", "ai_model": "qwen3:4b",
                 "stt_language": "ur", "tts_voice": "ur_PK-fasih-medium", "speak_responses": "voice_only",
                 "search_engine": "google", "browser_channel": "chrome", "project_folders": ["C:\\xampp\\htdocs"],
                 "history_days": 90, "reply_style": "auto", "emotion_awareness": True, "voice_signals": True,
                 "show_estimate": True, "learn_patterns": True, "suggest_routines": True,
                 "start_with_windows": False, "setup_done": False, "multi_pc": False,
                 "pc_name": ""}


def test_settings_partial_update_persists_and_logs(client):
    r = client.put("/api/settings", json={"assistant_name": "Zara", "startup_mode": "silent"})
    assert r.status_code == 200
    assert r.json()["assistant_name"] == "Zara"
    assert r.json()["wake_word"] == "Hey NOVA"  # untouched
    assert client.get("/api/settings").json()["startup_mode"] == "silent"
    assert client.get("/api/status").json()["assistant_name"] == "Zara"
    activity = client.get("/api/activity").json()[0]
    assert activity["action"] == "update_settings"
    assert activity["final_result"] == "assistant_name, startup_mode"


def test_settings_survive_restart(tmp_path):
    from conftest import build_client

    with build_client(tmp_path) as c:
        c.put("/api/settings", json={"assistant_name": "Zara", "wake_word": "Suno Zara"})
    with build_client(tmp_path) as c:
        assert c.get("/api/settings").json()["wake_word"] == "Suno Zara"
        assert c.get("/api/status").json()["assistant_name"] == "Zara"


@pytest.mark.parametrize(
    "payload",
    [
        {"assistant_name": ""},
        {"assistant_name": "x" * 25},
        {"assistant_name": "<script>"},
        {"wake_word": "a"},
        {"startup_mode": "loud"},
    ],
)
def test_settings_validation(client, payload):
    assert client.put("/api/settings", json=payload).status_code == 422
    assert client.get("/api/settings").json()["assistant_name"] == "NOVA"


def test_settings_accept_urdu_name(client):
    r = client.put("/api/settings", json={"assistant_name": "نووا", "wake_word": "سنو نووا"})
    assert r.status_code == 200
    assert r.json()["assistant_name"] == "نووا"


def test_custom_wake_word_is_stripped(client):
    client.put("/api/settings", json={"assistant_name": "Zara", "wake_word": "Suno Zara"})
    for text in ("Suno Zara, Chrome open karo", "Hey Zara Chrome open karo", "Zara, Chrome open karo"):
        body = client.post("/api/command", json={"text": text}).json()
        assert body["intent"]["name"] == "open_app", text
        assert body["intent"]["entities"]["app"] == "Chrome", text


def test_wake_pattern_does_not_eat_words_starting_with_name():
    provider = RuleBasedProvider()
    provider.configure_wake("Ali", "Hey Ali")
    intent = asyncio.run(provider.detect_intent("Alibaba open karo"))
    assert intent.entities["app"] == "Alibaba"


def test_greeting_uses_new_name(client):
    client.put("/api/settings", json={"assistant_name": "Zara"})
    body = client.post("/api/command", json={"text": "Assalam-o-Alaikum"}).json()
    assert "Zara online hai" in body["response"]


def _states_until(ws, target, limit=50):
    states = []
    for _ in range(limit):
        e = ws.receive_json()
        if e.get("type") == "STATE_CHANGED":
            states.append(e["data"]["state"])
            if e["data"]["state"] == target:
                return states
    raise AssertionError(f"never reached {target}: {states}")


def test_voice_state_switches_listening_and_returns_after_command(client):
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["data"]["voice_active"] is False
        ws.send_json({"type": "voice_state", "active": True})
        assert _states_until(ws, "LISTENING") == ["LISTENING"]
        assert client.get("/api/status").json()["state"] == "LISTENING"

        # A command while the mic is open returns to LISTENING, not IDLE.
        ws.send_json({"type": "command", "text": "Assalam-o-Alaikum"})
        assert _states_until(ws, "LISTENING") == ["THINKING", "PLANNING", "COMPLETED", "LISTENING"]

        ws.send_json({"type": "voice_state", "active": False})
        assert _states_until(ws, "IDLE") == ["IDLE"]


def test_disconnect_closes_mic_state(client):
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "voice_state", "active": True})
        _states_until(ws, "LISTENING")
    assert client.get("/api/status").json()["state"] == "IDLE"
