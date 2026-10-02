"""Phase 4: AI brain (Ollama provider, modes, fallbacks), task planner, orchestrated execution."""

import asyncio
import json

import httpx
import pytest

from conftest import FakeOllama
from nova.ai.manager import ProviderManager
from nova.ai.ollama import OllamaProvider, parse_model_output
from nova.ai.rule_based import RuleBasedProvider
from nova.planner import build_plan
from nova.ai.base import Intent, Understanding


def run(coro):
    return asyncio.run(coro)


def manager(fake: FakeOllama, mode="hybrid") -> ProviderManager:
    return ProviderManager(mode=mode, ollama=OllamaProvider(transport=fake.transport))


# ------------------------------------------------------------------ rules: compound commands


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Chrome kholo aur RAM batao", [("open_app", {"app": "Chrome"}), ("system_info", {"topic": "ram"})]),
        ("Open Chrome and search for web development",
         [("open_app", {"app": "Chrome"}), ("web_search", {"query": "web development"})]),
        ("Hey NOVA, windows version batao phir storage check karo",
         [("system_info", {"topic": "windows"}), ("system_info", {"topic": "storage"})]),
        ("mic aur camera check karo", [("system_info", {"topic": "devices"})]),  # not split: parts unclear
        ("VS Code open karo", [("open_app", {"app": "VS Code"})]),
        ("zara VS Code chala do", [("open_app", {"app": "VS Code"})]),
    ],
)
def test_rules_compound(text, expected):
    u = run(RuleBasedProvider().understand(text))
    assert [(i.name, i.entities) for i in u.intents] == expected


@pytest.mark.parametrize(
    "text,intent_name,entities",
    [
        ("please launch whatsapp for me", "open_app", {"app": "whatsapp"}),
        ("desktop par Projects naam ka folder bana do", "create_folder", {"folder_name": "Projects"}),
        ("zindagi kaisi chal rahi hai dost", "unknown", {}),  # not "running apps"
        ("kaun si apps chal rahi hain", "system_info", {"topic": "running"}),
    ],
)
def test_rule_entity_cleanup(text, intent_name, entities):
    i = run(RuleBasedProvider().detect_intent(text))
    assert (i.name, i.entities) == (intent_name, entities)


def test_pronoun_follow_up_goes_to_model_with_context(fake_ollama):
    fake_ollama.reply = lambda _t: {"intents": [{"name": "open_app", "app": "Photoshop"}], "answer": ""}
    from nova.ai.base import ConversationTurn

    ctx = [ConversationTurn(user="kya photoshop installed hai", assistant="Haan, Adobe Photoshop installed hai.")]
    u = run(manager(fake_ollama).understand("isko kholo", ctx))  # hybrid
    assert u.provider.startswith("ollama")
    assert u.intents[0].entities == {"app": "Photoshop"}


def test_long_sentences_lower_rule_confidence():
    short = run(RuleBasedProvider().detect_intent("RAM check karo"))
    long = run(RuleBasedProvider().detect_intent("yaar zara mujhe bata do ke mere system ki RAM kitni hai abhi"))
    assert short.confidence >= 0.8 > long.confidence


# ------------------------------------------------------------------ model output validation


def test_parse_valid_output():
    raw = json.dumps({"intents": [{"name": "open_app", "app": " VS   Code "}, {"name": "system_info", "topic": "ram"}],
                      "answer": "ignored"})
    intents, answer = parse_model_output(raw, "mixed", "ollama")
    assert [(i.name, i.entities) for i in intents] == [("open_app", {"app": "VS Code"}),
                                                        ("system_info", {"topic": "ram"})]
    assert answer is None  # answers are only kept for chat


def test_parse_rejects_unknown_intents_and_bad_fields():
    raw = json.dumps({"intents": [{"name": "format_disk"}, {"name": "system_info", "topic": "bitcoin"},
                                  {"name": "open_app", "app": "x" * 500}], "answer": ""})
    intents, _ = parse_model_output(raw, "en", "ollama")
    assert [i.name for i in intents] == ["system_info", "open_app"]
    assert intents[0].entities["topic"] == "summary"
    assert len(intents[1].entities["app"]) == 200


@pytest.mark.parametrize("raw", ["not json", "[]", '{"intents": []}', '{"intents": [{"name": "rm_rf"}]}'])
def test_parse_invalid_output_raises(raw):
    with pytest.raises(ValueError):
        parse_model_output(raw, "en", "ollama")


def test_chat_answer_kept_and_clipped():
    raw = json.dumps({"intents": [{"name": "chat"}], "answer": "Jawab " * 400})
    _, answer = parse_model_output(raw, "roman_ur", "ollama")
    assert answer and len(answer) <= 1200


# ------------------------------------------------------------------ manager modes and fallbacks


def test_rules_mode_never_calls_model(fake_ollama):
    u = run(manager(fake_ollama, "rules").understand("Pakistan ka capital kya hai"))
    assert u.provider == "rule_based"
    assert fake_ollama.chat_requests == []


def test_hybrid_uses_rules_for_clear_commands(fake_ollama):
    u = run(manager(fake_ollama).understand("RAM check karo"))
    assert u.provider == "rule_based"
    assert fake_ollama.chat_requests == []


def test_hybrid_uses_model_for_questions(fake_ollama):
    fake_ollama.reply = lambda _t: {"intents": [{"name": "chat"}], "answer": "Pakistan ka capital Islamabad hai."}
    u = run(manager(fake_ollama).understand("Pakistan ka capital kya hai"))
    assert u.provider == "ollama:qwen3:4b"
    assert u.intents[0].name == "chat"
    assert u.answer == "Pakistan ka capital Islamabad hai."
    sent = fake_ollama.chat_requests[0]
    assert sent["think"] is False and sent["stream"] is False and sent["options"]["temperature"] == 0
    assert sent["format"]["properties"]["intents"]["items"]["properties"]["name"]["enum"]


def test_llm_mode_sends_everything_to_model(fake_ollama):
    fake_ollama.reply = lambda _t: {"intents": [{"name": "system_info", "topic": "ram"}], "answer": ""}
    u = run(manager(fake_ollama, "llm").understand("RAM check karo"))
    assert u.provider.startswith("ollama")
    assert len(fake_ollama.chat_requests) == 1


@pytest.mark.parametrize(
    "setup,reason",
    [
        (lambda f: setattr(f, "models", []), "model_unavailable"),
        (lambda f: setattr(f, "reachable", False), "model_unavailable"),
        (lambda f: setattr(f, "reply", lambda _t: "this is not json"), "invalid_output"),
        # Prompt-injection style output: an action that does not exist is never accepted.
        (lambda f: setattr(f, "reply", lambda _t: {"intents": [{"name": "delete_all_files"}], "answer": ""}),
         "invalid_output"),
    ],
)
def test_fallback_to_rules(fake_ollama, setup, reason):
    setup(fake_ollama)
    u = run(manager(fake_ollama).understand("kuch samajh na aane wali baat"))
    assert u.provider == "rule_based"
    assert u.fallback_reason == reason


def test_timeout_falls_back(fake_ollama):
    def slow(_t):
        raise httpx.ReadTimeout("too slow")

    fake_ollama.reply = slow
    u = run(manager(fake_ollama).understand("Pakistan ka capital kya hai"))
    assert u.fallback_reason == "timeout"


def test_context_is_sent_to_model(fake_ollama):
    from nova.ai.base import ConversationTurn

    fake_ollama.reply = lambda _t: {"intents": [{"name": "open_app", "app": "Photoshop"}], "answer": ""}
    ctx = [ConversationTurn(user="kya photoshop installed hai", assistant="Haan, Photoshop installed hai.")]
    run(manager(fake_ollama, "llm").understand("isko kholo", ctx))
    prompt = fake_ollama.chat_requests[0]["messages"][-1]["content"]
    assert "Recent conversation" in prompt and "photoshop installed" in prompt and "isko kholo" in prompt


# ------------------------------------------------------------------ planner


def intent(name, **entities):
    return Intent(name=name, entities=entities)


def test_plan_statuses_and_risk():
    plan = build_plan(Understanding(intents=[intent("system_info", topic="ram"), intent("change_setting"),
                                             intent("create_folder"), intent("open_app", app="Chrome")],
                                    provider="test"))
    by_intent = {s.intent.name: s for s in plan.steps}
    assert by_intent["system_info"].status == "ready" and by_intent["system_info"].risk == "low"
    assert by_intent["change_setting"].status == "unavailable" and by_intent["change_setting"].available_from_phase == 8
    assert by_intent["create_folder"].risk == "medium" and by_intent["create_folder"].status != "ready"
    assert by_intent["open_app"].status == "ready" and by_intent["open_app"].risk == "low"
    assert [s.id for s in plan.steps] == [1, 2, 3, 4]


def test_plan_drops_greeting_next_to_real_request():
    plan = build_plan(Understanding(intents=[intent("greeting"), intent("system_info", topic="cpu")], provider="t"))
    assert [s.intent.name for s in plan.steps] == ["system_info"]


def test_unknown_intent_name_from_any_source_plans_as_unknown():
    plan = build_plan(Understanding(intents=[intent("format_c_drive")], provider="t"))
    assert plan.steps[0].action == "respond" and plan.steps[0].risk == "low"


# ------------------------------------------------------------------ end to end through the API


def test_chat_question_answered_by_model_without_execution(ai_client, fake_ollama):
    fake_ollama.reply = lambda _t: {"intents": [{"name": "chat"}], "answer": "Islamabad Pakistan ka capital hai."}
    body = ai_client.post("/api/command", json={"text": "Pakistan ka capital kya hai?"}).json()
    assert body["response"] == "Islamabad Pakistan ka capital hai."
    assert body["executed"] is False
    assert body["provider"] == "ollama:qwen3:4b"


def test_compound_command_plans_and_runs_each_step(ai_client, fake_ollama):
    fake_ollama.reply = lambda _t: {
        "intents": [{"name": "open_app", "app": "VS Code"}, {"name": "system_info", "topic": "ram"}], "answer": ""}
    ai_client.put("/api/settings", json={"ai_mode": "llm"})
    with ai_client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "command", "text": "zara VS Code chala do aur yeh bhi batao ke RAM kitni hai"})
        events = []
        while True:
            e = ws.receive_json()
            events.append(e)
            if e["type"] == "TASK_COMPLETED":
                break
    types = [e["type"] for e in events]
    plan = next(e for e in events if e["type"] == "PLAN_CREATED")
    assert [s["intent"] for s in plan["data"]["steps"]] == ["open_app", "system_info"]
    assert types.count("STEP_COMPLETED") == 2
    response = next(e for e in events if e["type"] == "NOVA_RESPONSE")["message"]
    assert response.startswith("Aapne 2 kaam bataye:")
    assert "1. Visual Studio Code khul gaya hai" in response
    assert "2. RAM: total 16 GB" in response
    rows = ai_client.get("/api/activity?limit=2").json()
    assert {r["execution_status"] for r in rows} == {"success"}
    assert {r["verification_status"] for r in rows} == {"passed", "not_applicable"}


def test_fallback_note_shown_for_unclear_text_without_model(client):
    body = client.post("/api/command", json={"text": "zindagi kaisi chal rahi hai dost"}).json()
    assert body["fallback_reason"] == "model_unavailable"
    assert "Local AI model abhi available nahi" in body["response"]


def test_ai_status_and_mode_switch(ai_client, fake_ollama):
    s = ai_client.get("/api/ai/status").json()
    assert s["mode"] == "hybrid" and s["model_ready"] is True and s["ollama"]["version"] == "0.35.0"
    # Startup warm-up sends one throwaway classification to cache the system prompt.
    assert any("Assalam" in r["messages"][-1]["content"] for r in fake_ollama.chat_requests)
    ai_client.put("/api/settings", json={"ai_mode": "rules"})
    assert ai_client.get("/api/ai/status").json()["mode"] == "rules"
    fake_ollama.chat_requests.clear()
    ai_client.post("/api/command", json={"text": "Pakistan ka capital kya hai"})
    assert fake_ollama.chat_requests == []


@pytest.mark.parametrize("payload", [{"ai_mode": "cloud"}, {"ai_model": "qwen3:4b; rm -rf"}, {"ai_model": ""}])
def test_ai_settings_validation(client, payload):
    assert client.put("/api/settings", json=payload).status_code == 422
