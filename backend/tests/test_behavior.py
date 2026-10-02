"""Phase 10: communication-state estimate (an estimate only), tone adaptation, habits, response personalization."""

import asyncio
import json
import math
from array import array
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from conftest import FakeDesktop, build_client
from nova.ai.ollama import parse_model_output
from nova.ai.rule_based import RuleBasedProvider
from nova.behavior.estimator import BehaviorEstimator, Turn
from nova.behavior.patterns import describe, find_routines, part_of_day, sessions, summary
from nova.behavior.signals import VoiceFeatures, is_simple_command, text_signals, voice_features
from nova.behavior.style import choose_style, compact, shape


def arun(coro):
    return asyncio.run(coro)


def cmd(client, text):
    return client.post("/api/command", json={"text": text}).json()


def last_reply(client):
    return [e for e in client.app.state.bus.history() if e.type.value == "NOVA_RESPONSE"][-1].data


def events(client, kind):
    return [e for e in client.app.state.bus.history() if e.type.value == kind]


def tone(speed=3.0, loud=-20.0, pitch=150.0):
    return VoiceFeatures(duration_s=2.0, voiced_s=1.5, words=int(speed * 1.5), rate_wps=speed, loudness_db=loud,
                         pitch_hz=pitch)


# ------------------------------------------------------------------ signals


@pytest.mark.parametrize("text,state", [
    ("kitni dafa kahun, Chrome kholo", "frustrated"),
    ("ye kaam hi nahi kar raha", "frustrated"),
    ("jaldi se Chrome kholo", "hurried"),
    ("foran report bhejo", "hurried"),
    ("samajh nahi aaya, file kaise kholoon", "confused"),
    ("shukriya NOVA", "positive"),
    ("main bohat thak gaya hoon", "tired"),
    ("جلدی کروم کھولو", "hurried"),
    ("شکریہ", "positive"),
])
def test_words_give_signals(text, state):
    assert state in {s.state for s in text_signals(text)}


def test_plain_commands_give_no_signals_and_are_simple():
    assert text_signals("Chrome kholo") == [] and is_simple_command("Chrome kholo")
    assert not is_simple_command("please zara mera system check kar dein")
    assert {s.state for s in text_signals("YE KAAM KARO ABHI")} == {"frustrated"}
    assert text_signals("NOVA ko HTML file do") == []  # known capitals are not shouting


def test_voice_features_from_audio():
    speech = array("h", (int(8000 * math.sin(2 * math.pi * 200 * i / 16000)) for i in range(32000))).tobytes()
    pcm = bytes(8000) + speech + bytes(16000)
    v = voice_features(pcm, "mera system check karo")
    assert v is not None and abs(v.pitch_hz - 200) < 10 and 1.8 < v.voiced_s < 2.2
    assert v.rate_wps == round(4 / v.voiced_s, 2) and -17 < v.loudness_db < -13
    assert voice_features(bytes(32000), "kuch") is None  # silence
    # A push-to-talk segment with almost no silence: the voice must not be taken for background noise.
    tight = voice_features(bytes(1600) + speech + bytes(1600), "mera system check karo")
    assert tight is not None and abs(tight.pitch_hz - 200) < 10 and tight.voiced_s > 1.8


# ------------------------------------------------------------------ estimate


def test_estimate_is_hedged_and_needs_real_evidence():
    est = BehaviorEstimator(clock=lambda: 100.0)
    assert est.estimate("Chrome kholo", []).state == "neutral"
    hurry = est.estimate("jaldi se Chrome kholo", [])
    assert hurry.state == "hurried" and hurry.label == "shayad jaldi mein" and hurry.reasons == ["jaldi wale alfaaz"]
    assert est.estimate("bas", []).state == "neutral"  # the earlier hint alone fades below the bar


def test_context_signals_repeat_and_failures():
    now = [1000.0]
    est = BehaviorEstimator(clock=lambda: now[0])
    turns = [Turn("Chrome kholo", "failed", 990.0)]
    e = est.estimate("Chrome kholo", turns)
    assert e.state == "frustrated" and "wahi baat dobara kahi" in e.reasons and "pichla jawab kaam ka nahi tha" in e.reasons
    turns = [Turn("a", "not_understood", 900.0), Turn("b", "failed", 950.0)]
    est = BehaviorEstimator(clock=lambda: now[0])
    assert est.estimate("ab RAM batao", turns).state == "frustrated"
    # Thanks outweighs earlier irritation.
    assert est.estimate("shukriya", turns).state == "positive"


def test_voice_is_compared_with_the_users_own_normal():
    est = BehaviorEstimator(clock=lambda: 0.0)
    for _ in range(3):
        assert est.estimate("RAM batao", [], tone()).state == "neutral"
    fast = est.estimate("mera system ki RAM batao", [], tone(speed=4.5))
    assert fast.state == "hurried" and fast.reasons == ["aam se tez bole"] and fast.confidence <= 0.6  # voice alone
    assert fast.label.startswith("shayad")
    est.forget_mood()
    tired = est.estimate("RAM batao", [], tone(speed=1.8, loud=-30))
    assert tired.state == "neutral" or tired.reasons == ["aam se dheere aur halki awaaz"]
    loud_angry = est.estimate("ye kya bakwas hai", [], tone(loud=-8, pitch=200))
    assert loud_angry.state == "frustrated" and "aam se zor se bole" in loud_angry.reasons


# ------------------------------------------------------------------ tone


def test_style_follows_the_estimate_and_the_users_choice():
    est = SimpleNamespace
    assert choose_style(est(state="frustrated"), "auto") == "calm"
    assert choose_style(est(state="hurried"), "auto") == "brief"
    assert choose_style(est(state="confused"), "auto") == "helpful"
    assert choose_style(est(state="neutral"), "auto") == "normal"
    assert choose_style(est(state="neutral"), "short") == "brief"
    assert choose_style(est(state="frustrated"), "short") == "calm"
    assert choose_style(est(state="neutral"), "detailed") == "detailed"


def test_shaping_keeps_the_facts():
    reply = ("'work' workflow save ho gaya (2 cheezein):\n1. Chrome (app)\nChalane ke liye kahein: \"work start karo\". "
             "(Verify: memory mein save hai.)")
    short = compact(reply)
    assert "Chalane ke liye" not in short and "(Verify" not in short and "✓" in short and "Chrome (app)" in short
    text, speech = shape("Maaf kijiye, main ye command abhi samajh nahi saka.", "calm", outcome="not_understood",
                         intents=["unknown"], simple=False)
    assert text.startswith("Maaf kijiye, main") and "Seedha aise kahein" in text and speech
    text, _ = shape("Chrome nahi khula.", "calm", outcome="failed", intents=["open_app"], simple=False)
    assert text.startswith("Maaf kijiye. Chrome") and "dobara karo" in text
    text, speech = shape("Chrome khul gaya hai. (Verify: window \"Chrome\" 1.2s mein nazar aayi.)", "brief",
                         outcome="done", intents=["open_app"], simple=True)
    assert text == "Chrome khul gaya hai. ✓" and speech == "Chrome khul gaya hai."
    text, speech = shape("File nahi mili.", "helpful", outcome="answered", intents=["search_files"], simple=False)
    assert "Misaal" in text and "pdf" in text and speech is None
    text, speech = shape("RAM: 16 GB.", "normal", outcome="answered", intents=["system_info"], simple=False)
    assert (text, speech) == ("RAM: 16 GB.", None)


# ------------------------------------------------------------------ habits


def usage(day, hour, minute, kind, target):
    when = datetime(2026, 10, day, hour, minute)
    return {"created_at": when.isoformat(timespec="seconds"), "kind": kind, "target": target}


def morning(day):
    return [usage(day, 9, 0, "app", "Google Chrome"), usage(day, 9, 2, "app", "Visual Studio Code"),
            usage(day, 9, 3, "website", "github.com"), usage(day, 9, 4, "command", "open_app")]


def test_routines_need_several_days():
    now = datetime(2026, 10, 3, 12, 0)
    events = morning(1) + morning(2) + morning(3) + [usage(3, 21, 0, "app", "Google Chrome")]
    assert len(sessions(events)) == 4
    routines = find_routines(events, now)
    assert len(routines) == 1
    r = routines[0]
    assert r.labels == ["Google Chrome", "Visual Studio Code", "github.com"] and r.days == 3 and r.name == "subah"
    assert find_routines(morning(1) + morning(2), now) == []  # only 2 days
    covered = [{("app", "Google Chrome"), ("app", "Visual Studio Code"), ("website", "github.com")}]
    assert find_routines(events, now, covered=covered) == []
    # "nahi" also covers the smaller parts of that routine
    assert find_routines(events, now, declined={r.key}) == []
    old = morning(1) + morning(2) + morning(3)
    assert find_routines(old, now + timedelta(days=40)) == []  # older than 30 days
    assert part_of_day(14) == "dopahar" and part_of_day(23) == "raat"


def test_habit_summary():
    now = datetime(2026, 10, 3, 12, 0)
    data = summary(morning(1) + morning(2), now)
    assert data["items"][0] == {"kind": "app", "target": "Google Chrome", "count": 2, "days": 2, "usual_time": "subah"}
    assert data["commands"] == [{"intent": "open_app", "count": 2}]
    assert "Google Chrome: 2 dafa" in describe(data) and "apps kholna" in describe(data)
    assert "koi aadat" in describe(summary([], now))


# ------------------------------------------------------------------ understanding


@pytest.mark.parametrize("text,name,entities", [
    ("shukriya", "thanks", {}),
    ("bohat shukriya NOVA", "thanks", {}),
    ("zabardast kaam kiya", "thanks", {}),
    ("chhote jawab diya karo", "set_reply_style", {"style": "short"}),
    ("ab se tafseel se bataya karo", "set_reply_style", {"style": "detailed"}),
    ("ab se har cheez tafseel se samjhaya karo", "set_reply_style", {"style": "detailed"}),
    ("normal jawab diya karo", "set_reply_style", {"style": "auto"}),
    ("meri aadatein batao", "show_patterns", {}),
    ("main aksar kya kholta hoon", "show_patterns", {}),
    ("meri aadatein bhool jao", "forget_memory", {"scope": "patterns"}),
])
def test_rules_understand_behavior_commands(text, name, entities):
    u = arun(RuleBasedProvider().understand(text))
    assert [(i.name, i.entities) for i in u.intents] == [(name, entities)]


def test_model_output_for_reply_style():
    raw = json.dumps({"intents": [{"name": "set_reply_style", "reply_style": "short"}], "answer": ""})
    assert parse_model_output(raw, "roman_urdu", "ollama")[0][0].entities == {"style": "short"}
    raw = json.dumps({"intents": [{"name": "set_reply_style", "reply_style": "loud"}], "answer": ""})
    assert parse_model_output(raw, "roman_urdu", "ollama")[0][0].entities == {}


# ------------------------------------------------------------------ through NOVA


@pytest.fixture
def env(tmp_path):
    desktop = FakeDesktop()
    with build_client(tmp_path, desktop=desktop, permission_timeout_s=10) as client:
        yield SimpleNamespace(client=client, desktop=desktop)


def test_hurried_command_gets_a_short_reply_and_a_visible_estimate(env):
    c = env.client
    body = cmd(c, "jaldi se Chrome kholo")
    reply = last_reply(c)
    assert reply["estimate"]["state"] == "hurried" and reply["estimate"]["label"] == "shayad jaldi mein"
    assert reply["style"] == "brief" and "(Verify" not in body["response"] and "✓" in body["response"]
    assert reply["speech"] and "Verify" not in reply["speech"]
    note = events(c, "BEHAVIOR_ESTIMATED")[-1]
    assert note.agent == "Behavior Layer" and note.message.startswith("Andaza (sirf andaza): shayad jaldi mein")
    c.put("/api/settings", json={"show_estimate": False})
    cmd(c, "jaldi se RAM batao")
    assert last_reply(c)["estimate"] is None and last_reply(c)["style"] == "brief"  # still adapts, not shown
    c.put("/api/settings", json={"emotion_awareness": False})
    cmd(c, "jaldi se RAM batao")
    assert last_reply(c)["style"] == "normal"


def test_repeated_failure_gets_a_calm_reply_with_a_next_step(env):
    c = env.client
    first = cmd(c, "flibber jabber quux")
    assert "Seedha aise kahein" not in first["response"]
    second = cmd(c, "flibber jabber quux")
    assert last_reply(c)["estimate"]["state"] == "frustrated" and last_reply(c)["style"] == "calm"
    assert second["response"].startswith("Maaf kijiye") and "Seedha aise kahein" in second["response"]
    reasons = last_reply(c)["estimate"]["reasons"]
    assert "wahi baat dobara kahi" in reasons


def test_thanks_and_reply_style_preference(env):
    c = env.client
    assert cmd(c, "shukriya")["response"] == "Koi baat nahi! Aur koi kaam ho to batayein."
    c.post("/api/memory/facts", json={"text": "mera naam Ahmed hai"})
    assert cmd(c, "bohat shukriya")["response"].startswith("Koi baat nahi, Ahmed!")
    body = cmd(c, "chhote jawab diya karo")
    assert "chhote dunga" in body["response"] and "Verify" in body["response"]
    assert c.get("/api/settings").json()["reply_style"] == "short"
    assert "pehle se chhote" in cmd(c, "chhote jawab diya karo")["response"]
    body = cmd(c, "Chrome kholo")
    assert "(Verify" not in body["response"] and "✓" in body["response"] and last_reply(c)["style"] == "brief"
    cmd(c, "normal jawab diya karo")
    assert c.get("/api/settings").json()["reply_style"] == "auto"
    assert "(Verify" in cmd(c, "Chrome kholo")["response"]


def test_habits_are_recorded_shown_and_forgotten(env):
    c = env.client
    cmd(c, "Chrome kholo")
    cmd(c, "VS Code kholo")
    cmd(c, "RAM batao")
    data = c.get("/api/behavior/patterns").json()
    targets = {i["target"] for i in data["items"]}
    assert {"Google Chrome", "Visual Studio Code"} <= targets and data["learning"] is True
    assert {"intent": "system_info", "count": 1} in data["commands"]
    assert "Google Chrome: 1 dafa" in cmd(c, "meri aadatein batao")["response"]
    t_body = {}
    import threading
    import time
    t = threading.Thread(target=lambda: t_body.update(cmd(c, "meri aadatein bhool jao")))
    t.start()
    req = None
    for _ in range(100):
        pending = c.get("/api/permissions/pending").json()
        if pending:
            req = pending[0]
            break
        time.sleep(0.05)
    assert req and req["max_risk"] == "medium" and not req["rememberable"]
    c.post(f"/api/permissions/{req['id']}/decision", json={"approved": True})
    t.join()
    assert "Aadatein bhool gaya" in t_body["response"]
    assert c.get("/api/behavior/patterns").json()["items"] == []
    c.put("/api/settings", json={"learn_patterns": False})
    cmd(c, "Chrome kholo")
    assert c.app.state.db.list_usage() == []  # learning switched off: nothing recorded
    assert "band hai" in cmd(c, "meri aadatein batao")["response"]


def seed_two_mornings(db):
    for days_ago in (1, 2):
        day = datetime.now() - timedelta(days=days_ago)
        for minute, (kind, target) in enumerate([("app", "Google Chrome"), ("app", "Visual Studio Code")]):
            when = day.replace(hour=9, minute=minute, second=0, microsecond=0)
            db._execute("INSERT INTO usage_events(created_at, kind, target) VALUES (?, ?, ?)",
                        (when.isoformat(timespec="seconds"), kind, target))


def test_a_routine_is_offered_once_and_saved_only_on_haan(env):
    c = env.client
    seed_two_mornings(c.app.state.db)
    assert "workflow bana doon" not in cmd(c, "Chrome kholo")["response"]
    body = cmd(c, "VS Code kholo")
    assert "Main ne dekha hai aap aksar" in body["response"] and "workflow bana doon?" in body["response"]
    assert last_reply(c)["quick_replies"] == ["Haan", "Nahi"]
    cmd(c, "haan")
    saved = c.get("/api/workflows").json()
    assert len(saved) == 1 and [s["label"] for s in saved[0]["steps"]] == ["Google Chrome", "Visual Studio Code"]
    assert c.get("/api/behavior/patterns").json()["routines"] == []  # now covered by the workflow
    assert "workflow bana doon" not in cmd(c, "Chrome kholo")["response"]


def test_a_declined_routine_is_not_offered_again(env):
    c = env.client
    seed_two_mornings(c.app.state.db)
    cmd(c, "Chrome kholo")
    cmd(c, "VS Code kholo")
    assert cmd(c, "nahi")["response"] == "Theek hai, ye tajweez dobara nahi doonga."
    assert c.get("/api/workflows").json() == [] and c.app.state.db.declined_routines()
    assert c.get("/api/behavior/patterns").json()["routines"] == []
    c.app.state.behavior.suggested = False  # even in a new session
    assert "workflow bana doon" not in cmd(c, "VS Code kholo")["response"]


def test_habits_api_and_history_deletion(env):
    c = env.client
    cmd(c, "Chrome kholo")
    assert c.app.state.db.list_usage()
    assert c.delete("/api/behavior/patterns").json()["removed"] >= 1 and c.app.state.db.list_usage() == []
    cmd(c, "Chrome kholo")
    c.delete("/api/history")  # deleting the history deletes the habits learned from it too
    assert c.app.state.db.list_usage() == []
    assert c.post("/api/behavior/routines/decline", json={"key": "app:x|app:y"}).json() == {"ok": True}
    assert "app:x|app:y" in c.app.state.db.declined_routines()


def test_chat_answers_get_a_style_hint(tmp_path):
    from conftest import FakeOllama

    ollama = FakeOllama(models=["qwen3:4b"])
    ollama.reply = lambda text: {"intents": [{"name": "chat"}], "answer": "Python ek programming language hai."}
    with build_client(tmp_path, ollama) as c:
        cmd(c, "jaldi batao python kya hoti hai aur kis kaam aati hai")
        prompt = ollama.chat_requests[-1]["messages"][-1]["content"]
        assert "Style for a chat answer: The user is in a hurry" in prompt
        cmd(c, "quantum physics kya hoti hai aur iska istemal kahan hota hai")
        assert "Style for a chat answer" not in ollama.chat_requests[-1]["messages"][-1]["content"]
