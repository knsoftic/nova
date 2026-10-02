"""Phase 7: Permission Engine - classification, asking, answering (UI/text/voice), memory, audit."""

import asyncio
import threading
import time

import pytest

from conftest import FakeDesktop, FakeOllama, build_client
from nova.permissions.engine import TargetContext, classify, parse_answer, scope_for


# ------------------------------------------------------------------ classification


@pytest.mark.parametrize(
    "intent,entities,process,title,risk",
    [
        ("type_text", {"text": "hello"}, "Notepad.exe", "notes.txt - Notepad", "medium"),
        ("type_text", {"text": "dir"}, "WindowsTerminal.exe", "Terminal", "high"),
        ("type_text", {"text": "my password is x"}, "Notepad.exe", "n", "high"),
        ("type_text", {"text": "4111111111111111"}, "chrome.exe", "Checkout", "high"),
        ("keyboard_shortcut", {"keys": "enter"}, "powershell.exe", "PowerShell", "high"),
        ("keyboard_shortcut", {"keys": "paste"}, "Notepad.exe", "n", "medium"),
        ("mouse_click", {"target": "OK"}, "Notepad.exe", "n", "medium"),
        ("mouse_click", {"target": "Delete account"}, "chrome.exe", "Settings", "high"),
        ("mouse_click", {"target": "Send"}, "WhatsApp.exe", "WhatsApp", "high"),
        ("mouse_click", {"target": "Pay now"}, "chrome.exe", "Shop", "high"),
        ("close_app", {"app": "Notepad"}, "Notepad.exe", "*notes.txt - Notepad", "medium"),
    ],
)
def test_classify(intent, entities, process, title, risk):
    got, reasons = classify(intent, entities, "medium", TargetContext(title=title, process=process))
    assert got == risk
    if risk == "high":
        assert reasons


def test_close_with_unsaved_marker_explains_why():
    _, reasons = classify("close_app", {"app": "Notepad"}, "medium", TargetContext("*notes.txt - Notepad", "Notepad.exe"))
    assert any("unsaved" in r for r in reasons)


def test_scope_is_narrow():
    t = TargetContext("notes.txt - Notepad", "Notepad.exe")
    assert scope_for("type_text", {"text": "a"}, t) == "type@notepad.exe"
    assert scope_for("keyboard_shortcut", {"keys": "paste"}, t) == "paste@notepad.exe"
    assert scope_for("mouse_click", {"target": "OK"}, t) == "click:ok@notepad.exe"
    assert scope_for("close_app", {"app": "Notepad"}, t) == "close:notepad"


@pytest.mark.parametrize(
    "text,answer",
    [("haan", True), ("Haan karo", True), ("ji haan", True), ("theek hai", True), ("yes", True), ("ok", True),
     ("ہاں", True), ("जी", True), ("nahi", False), ("mat karo", False), ("no", False), ("نہیں", False),
     ("cancel", False), ("Chrome kholo", None), ("haan Chrome bhi kholo", None), ("", None)],
)
def test_parse_answer(text, answer):
    assert parse_answer(text) is answer


# ------------------------------------------------------------------ the full flow through the API


def run_async(client, text, results):
    results.append(client.post("/api/command", json={"text": text}).json())


def ask(client, text, timeout=10.0):
    """Send a risky command in the background and return (thread, results, pending request)."""
    results: list[dict] = []
    t = threading.Thread(target=run_async, args=(client, text, results))
    t.start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = client.get("/api/permissions/pending").json()
        if pending:
            return t, results, pending[0]
        time.sleep(0.02)
    raise AssertionError("no permission request appeared")


@pytest.fixture
def perm_client(tmp_path):
    desktop = FakeDesktop()
    with build_client(tmp_path, desktop=desktop, permission_timeout_s=10) as client:
        yield client, desktop


def test_question_names_the_action_and_target(perm_client):
    client, desktop = perm_client
    t, results, req = ask(client, "hello world type karo")
    assert req["max_risk"] == "medium" and req["rememberable"] is True
    assert "Text type karna" in req["question"] and "hello world" in req["question"]
    assert "Inbox - Google Chrome" in req["question"]  # the window it would type into
    assert client.get("/api/status").json()["state"] == "WAITING_FOR_PERMISSION"
    assert desktop.calls == []  # nothing happens while waiting
    client.post(f"/api/permissions/{req['id']}/decision", json={"approved": False})
    t.join()


def test_approve_runs_and_verifies(perm_client):
    client, desktop = perm_client
    desktop.typed_field_value = ""  # field reports what was typed
    t, results, req = ask(client, "hello world type karo")
    assert client.post(f"/api/permissions/{req['id']}/decision", json={"approved": True}).json() == {"ok": True}
    t.join()
    body = results[0]
    assert body["executed"] is True and "likh diya" in body["response"] and "Verify" in body["response"]
    assert ("focus", 101) in desktop.calls and ("type", "hello world") in desktop.calls
    row = client.get("/api/activity?limit=1").json()[0]
    assert (row["permission_status"], row["verification_status"]) == ("approved_by_user", "passed")


def test_deny_does_nothing(perm_client):
    client, desktop = perm_client
    t, results, req = ask(client, "Chrome band karo")
    client.post(f"/api/permissions/{req['id']}/decision", json={"approved": False})
    t.join()
    assert "ijazat nahi mili" in results[0]["response"] and results[0]["executed"] is False
    assert desktop.calls == []
    assert client.get("/api/activity?limit=1").json()[0]["permission_status"] == "denied"


def test_typed_haan_answers_the_question(perm_client):
    client, desktop = perm_client
    t, results, req = ask(client, "Chrome band karo")
    answer = client.post("/api/command", json={"text": "haan"}).json()
    assert answer["status"] == "permission_answer"
    t.join()
    assert ("close", 101) in desktop.calls and "band ho gaya" in results[0]["response"]
    history = client.get("/api/permissions/history").json()[0]
    assert (history["decision"], history["decided_by"]) == ("approved", "user_text")


def test_remembered_approval_skips_the_question_next_time(perm_client):
    client, desktop = perm_client
    t, results, req = ask(client, "paste karo")
    client.post(f"/api/permissions/{req['id']}/decision", json={"approved": True, "remember": True})
    t.join()
    rules = client.get("/api/permissions/rules").json()
    assert len(rules) == 1 and rules[0]["scope"] == "paste@chrome.exe"
    # Same action in the same app: runs without asking.
    body = client.post("/api/command", json={"text": "paste karo"}).json()
    assert body["executed"] is True and desktop.calls.count(("hotkey", "paste")) == 2
    assert client.get("/api/activity?limit=1").json()[0]["permission_status"] == "approved_by_saved_rule"
    # Revoking brings the question back.
    assert client.delete(f"/api/permissions/rules/{rules[0]['id']}").json() == {"ok": True}
    t, results, req = ask(client, "paste karo")
    client.post(f"/api/permissions/{req['id']}/decision", json={"approved": False})
    t.join()


def test_high_risk_is_never_remembered(perm_client):
    client, desktop = perm_client
    t, results, req = ask(client, "Delete par click karo")
    assert req["max_risk"] == "high" and req["rememberable"] is False and "khatarnak" in req["question"]
    client.post(f"/api/permissions/{req['id']}/decision", json={"approved": True, "remember": True})
    t.join()
    assert client.get("/api/permissions/rules").json() == []  # "remember" ignored for high risk
    assert ("find_element", 101, "Delete") in desktop.calls
    t, results, req = ask(client, "Delete par click karo")  # asked again
    client.post(f"/api/permissions/{req['id']}/decision", json={"approved": False})
    t.join()


def test_timeout_means_no(tmp_path):
    desktop = FakeDesktop()
    with build_client(tmp_path, desktop=desktop, permission_timeout_s=0.3) as client:
        body = client.post("/api/command", json={"text": "hello type karo"}).json()
        assert "jawab nahi aaya" in body["response"] and desktop.calls == []
        assert client.get("/api/permissions/history").json()[0]["decision"] == "timeout"


def test_compound_asks_once_and_runs_safe_steps(perm_client):
    client, desktop = perm_client
    t, results, req = ask(client, "RAM batao aur hello type karo")
    assert len(req["items"]) == 1  # only the risky step is asked about
    client.post(f"/api/permissions/{req['id']}/decision", json={"approved": False})
    t.join()
    response = results[0]["response"]
    assert "RAM: total 16 GB" in response and "ijazat nahi mili" in response


def test_decision_on_unknown_request_is_404(perm_client):
    client, _ = perm_client
    assert client.post("/api/permissions/nope/decision", json={"approved": True}).status_code == 404


def test_click_falls_back_to_mouse_and_reports_missing_elements(perm_client):
    client, desktop = perm_client
    desktop.element_status = "found"  # control cannot be invoked: real mouse click at its centre
    t, results, req = ask(client, "OK par click karo")
    client.post(f"/api/permissions/{req['id']}/decision", json={"approved": True})
    t.join()
    assert ("click", 300, 400) in desktop.calls
    desktop.element_status = "not_found"
    t, results, req = ask(client, "Cancel par click karo")
    client.post(f"/api/permissions/{req['id']}/decision", json={"approved": True})
    t.join()
    assert "nahi mila" in results[0]["response"]


def test_close_that_does_not_close_is_reported(perm_client):
    client, desktop = perm_client
    desktop.close_works = False
    t, results, req = ask(client, "Notepad band karo")
    client.post(f"/api/permissions/{req['id']}/decision", json={"approved": True})
    t.join()
    assert "abhi khuli hai" in results[0]["response"]
    assert client.get("/api/activity?limit=1").json()[0]["verification_status"] == "failed"


def test_window_hosting_novas_ui_is_never_the_target(perm_client):
    """Regression: during development NOVA's UI ran inside another app's window (a browser pane); typing
    went into that host window. The window in front when a command is typed is NOVA's UI - skip it."""
    client, desktop = perm_client
    desktop.foreground = 101  # NOVA's UI is shown inside the Chrome window (hwnd 101)
    t, results, req = ask(client, "hello type karo")
    assert "notes.txt - Notepad" in req["question"] and "Chrome" not in req["question"]
    client.post(f"/api/permissions/{req['id']}/decision", json={"approved": True})
    t.join()
    assert ("focus", 102) in desktop.calls and ("focus", 101) not in desktop.calls
    # "screen par kya hai" also reads the user's window, not NOVA's.
    client.post("/api/command", json={"text": "screen par kya hai"})
    assert ("read", 102) in desktop.calls


def test_voice_commands_do_not_mark_the_front_window(perm_client):
    """A voice command can come while the user works in another app: that app stays the target."""
    client, desktop = perm_client
    desktop.foreground = 101
    agent = client.app.state.orchestrator.computer
    agent.note_command("voice")
    assert agent.ui_windows == set()


def test_agent_refuses_risky_action_without_approval_flag():
    from nova.agents.computer import ComputerAgent
    from nova.ai.base import Intent

    agent = ComputerAgent(FakeDesktop(), lambda: None, None)
    with pytest.raises(PermissionError):
        agent.run(Intent(name="type_text", entities={"text": "x"}))
    with pytest.raises(PermissionError):
        agent.run(Intent(name="keyboard_shortcut", entities={"keys": "paste"}))


def test_permission_question_is_spoken_for_voice_tasks(tmp_path):
    """The question goes through the same speech path as replies (asserted via the event bus)."""
    from nova.events import EventType

    with build_client(tmp_path, permission_timeout_s=10) as client:
        t, results, req = ask(client, "hello type karo")
        events = [e for e in client.app.state.bus.history() if e.type == EventType.PERMISSION_REQUIRED]
        assert events and events[-1].message == req["question"]
        client.post(f"/api/permissions/{req['id']}/decision", json={"approved": False})
        t.join()
