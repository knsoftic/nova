import pytest
from starlette.websockets import WebSocketDisconnect

from nova.redaction import REDACTED, redact


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_status_reports_honest_capabilities(client):
    data = client.get("/api/status").json()
    assert data["assistant_name"] == "NOVA"
    assert data["state"] == "IDLE"
    assert data["capabilities"]["system_discovery"] is True
    assert data["capabilities"]["computer_control"] is True
    assert data["capabilities"]["permission_engine"] is True


def test_open_app_is_executed_and_reported_in_roman_urdu(client):
    r = client.post("/api/command", json={"text": "Open Chrome"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"]["name"] == "open_app"
    assert body["executed"] is True
    assert "Google Chrome khul gaya hai" in body["response"]


def test_command_validation(client):
    assert client.post("/api/command", json={"text": ""}).status_code == 422
    assert client.post("/api/command", json={"text": "x" * 2001}).status_code == 422


def test_command_is_logged_and_redacted(client):
    client.post("/api/command", json={"text": "my password is hunter2 open chrome"})
    convo = client.get("/api/conversations").json()[0]
    assert "hunter2" not in convo["user_text"]
    activity = client.get("/api/activity").json()[0]
    assert activity["admin_status"] == "pending"
    assert activity["execution_status"] == "responded"  # words only, nothing executed
    for field in ("date", "time", "task_id", "agent", "permission_status", "verification_status"):
        assert activity[field]


def test_websocket_event_flow(client):
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "HELLO"
        assert hello["data"]["state"] == "IDLE"

        ws.send_json({"type": "command", "text": "Hey NOVA, VS Code open karo"})
        seen = []
        while True:
            event = ws.receive_json()
            seen.append(event)
            if event["type"] == "STATE_CHANGED" and event["data"]["state"] == "IDLE":
                break

    types = [e["type"] for e in seen]
    assert types.index("TASK_STARTED") < types.index("INTENT_DETECTED") < types.index("TASK_COMPLETED")
    states = [e["data"]["state"] for e in seen if e["type"] == "STATE_CHANGED"]
    assert states == ["THINKING", "PLANNING", "WORKING", "VERIFYING", "COMPLETED", "IDLE"]
    assert types.index("ACTION_EXECUTED") < types.index("VERIFICATION_STARTED") < types.index("VERIFICATION_PASSED")
    response = next(e for e in seen if e["type"] == "NOVA_RESPONSE")
    assert "Visual Studio Code khul gaya hai" in response["message"]


def test_websocket_rejects_foreign_origin(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()


def test_websocket_ping(client):
    with client.websocket_connect("/ws", headers={"origin": "http://localhost:5173"}) as ws:
        ws.receive_json()
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"


@pytest.mark.parametrize(
    "text",
    [
        "password: hunter2",
        "api_key=abc123",
        "Authorization: Bearer abc.def.ghi",
        "use sk-abcdefghijklmnopqrstuvwxyz",
    ],
)
def test_redaction(text):
    out = redact(text)
    assert REDACTED in out
    assert "hunter2" not in out and "abc123" not in out and "abcdefghijklmnop" not in out
