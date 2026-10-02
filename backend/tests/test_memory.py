"""Phase 9: short-term memory, long-term memory (user-approved only), conversation history, workflow memory."""

import asyncio
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import FakeBrowser, FakeDesktop, FakeOllama, FakeSettings, build_client, files_root
from nova.ai.base import KNOWN_INTENTS
from nova.ai.ollama import _schema, parse_model_output
from nova.ai.rule_based import RuleBasedProvider
from nova.memory import facts as F
from nova.memory.history import outcome, period_range, search_terms
from nova.memory.short_term import ShortTermMemory
from nova.memory.workflows import StepResolver, WorkflowStep, merge, split_items, workflow_key
from nova.discovery.models import AppEntry


def arun(coro):
    return asyncio.run(coro)


def cmd(client, text):
    return client.post("/api/command", json={"text": text}).json()


def ask(client, text, timeout=10.0):
    results = []
    t = threading.Thread(target=lambda: results.append(cmd(client, text)))
    t.start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = client.get("/api/permissions/pending").json()
        if pending:
            return t, results, pending[0]
        if not t.is_alive():
            return t, results, None
        time.sleep(0.05)
    return t, results, None


def decide(client, req, approved, remember=False):
    client.post(f"/api/permissions/{req['id']}/decision", json={"approved": approved, "remember": remember})


def facts(client):
    return [m["text"] for m in client.get("/api/memory/facts").json()]


def events(client, kind):
    return [e for e in client.app.state.bus.history() if e.type.value == kind]


@pytest.fixture
def env(tmp_path):
    fakes = SimpleNamespace(desktop=FakeDesktop(), browser=FakeBrowser(), settings=FakeSettings(), opened=[])
    with build_client(tmp_path, desktop=fakes.desktop, browser=fakes.browser, settings=fakes.settings,
                      opened=fakes.opened, permission_timeout_s=10) as client:
        fakes.client = client
        fakes.root = files_root(tmp_path)
        yield fakes


# ------------------------------------------------------------------ facts


@pytest.mark.parametrize("text,slot,value", [
    ("mera naam Ahmed hai", "name", "Ahmed"),
    ("mera naam ahmed raza hai", "name", "Ahmed Raza"),
    ("my name is Sara", "name", "Sara"),
    ("mujhe Sir kaha karo", "name", "Sir"),
    ("main Lahore mein rehta hoon", "city", "Lahore"),
    ("meri company ka naam KN Softic hai", "work", "KN Softic"),
    ("meri birthday 5 March ko hai", "birthday", "5 March"),
    ("mujhe chai bohat pasand hai", None, "chai"),
    ("mujhe karela pasand nahi", None, "karela"),
])
def test_personal_statements_worth_suggesting(text, slot, value):
    fact = F.detect_fact(text)
    assert fact is not None and fact.slot == slot and fact.value == value and fact.text == text


@pytest.mark.parametrize("text", ["mera naam kya hai", "mujhe ye pasand hai", "mujhe kya pasand hai",
                                  "mera laptop slow hai", "main theek hoon", "kya aap ko chai pasand hai"])
def test_questions_and_vague_statements_are_not_facts(text):
    assert F.detect_fact(text) is None


@pytest.mark.parametrize("text", ["mera password abc12345 hai", "mera ATM pin 4321 hai", "OTP 123456 hai",
                                  "mera card number 4111 1111 1111 1111 hai", "card 4111111111111111",
                                  "CNIC 35202-1234567-1", "meri api key sk-123 hai", "Ali ka number 03001234567 hai"])
def test_secrets_are_never_remembered(text):
    assert "yaad nahi rakhta" in F.problem(text)


def test_fact_size_limits_and_recall_ranking():
    assert F.problem("ok") and F.problem("x" * 400) and F.problem("mujhe chai pasand hai") is None
    memories = [{"id": 1, "text": "mujhe chai pasand hai"}, {"id": 2, "text": "meri wife ki birthday 5 March ko hai"},
                {"id": 3, "text": "Ali ki shaadi December mein hai"}]
    assert [m["id"] for m in F.rank("biwi ki salgirah kab hai", memories)] == [2]  # synonyms
    assert [m["id"] for m in F.rank("chai", memories)] == [1]
    assert F.rank("mera kya hai", memories) == []  # stopwords only
    # Only the best match: a memory that merely shares one word ("nova") is not picked too (live test finding).
    shared = [{"id": 1, "text": "nova meeting jummay ko hai"}, {"id": 2, "text": "nova mujhe biryani pasand hai"}]
    assert [m["id"] for m in F.rank("nova meeting wali baat", shared)] == [1]
    assert F.slot_of("mera naam kya hai") == "name" and F.slot_of("main kahan rehta hoon") == "city"


# ------------------------------------------------------------------ short-term memory


def test_short_term_memory_forgets_after_a_pause_and_questions_expire():
    now = [0.0]
    stm = ShortTermMemory(idle_reset_s=60, clock=lambda: now[0])
    cleared = []
    stm.on_clear(lambda: cleared.append(True))
    stm.touch()
    stm.add_turn("Chrome kholo", "Chrome khul gaya")
    stm.ask("remember", "Ye yaad rakhoon?", {"fact": "x"}, ttl_s=30)
    assert stm.turns() and stm.last_command == "Chrome kholo"
    now[0] = 40
    assert stm.take_pending() is None  # too old to answer
    stm.ask("remember", "Ye yaad rakhoon?", {"fact": "x"}, ttl_s=30)
    assert stm.take_pending() is not None and stm.take_pending() is None  # one answer per question
    stm.add_turn("haan", "Theek hai", command=False)
    assert stm.last_command == "Chrome kholo"  # answers are not commands
    now[0] = 200
    stm.touch()
    assert not stm.turns() and stm.last_command is None and cleared


# ------------------------------------------------------------------ workflows (unit)


def test_workflow_names_and_items():
    assert workflow_key("Work Environment") == "work" and workflow_key("kaam") == "work"
    assert workflow_key("'Study' workflow") == "study"
    assert split_items("Chrome, VS Code aur WhatsApp kholo") == ["Chrome", "VS Code", "WhatsApp"]
    assert split_items("open my Photoshop app and github.com") == ["Photoshop", "github.com"]


def test_step_resolver(tmp_path):
    apps = [AppEntry(name="Google Chrome", sources=["start_menu"]), AppEntry(name="Visual Studio Code", sources=[])]
    project = tmp_path / "shop-app"
    project.mkdir()
    resolver = StepResolver(apps=lambda: apps,
                            projects=lambda name: project if name == "shop app" else None,
                            folder=lambda name: tmp_path if name.lower() == "downloads" else SimpleNamespace(
                                message=f"\"{name}\" folder nahi mila."),
                            site_for=lambda name: "youtube.com" if name.lower() == "youtube" else None)
    steps, problems = resolver.resolve_all("Chrome, VS Code, YouTube, github.com, shop app project, Downloads folder, "
                                           "volume 30, FooApp, Chrome")
    assert [(s.kind, s.value) for s in steps] == [
        ("app", "Google Chrome"), ("app", "Visual Studio Code"), ("website", "youtube.com"), ("website", "github.com"),
        ("project", "shop-app"), ("folder", str(tmp_path)), ("setting", "30")]
    assert problems == ["\"FooApp\" na is PC par app mili, na website/project/folder"]
    intents = [s.intent("roman_urdu") for s in steps]
    assert [i.name for i in intents] == ["open_app", "open_app", "open_website", "open_website", "open_project",
                                         "open_file", "change_setting"]
    assert intents[-1].entities == {"setting": "volume", "value": "30"}
    chrome, code = steps[0], steps[1]
    assert merge([chrome], [code, chrome], "add") == [chrome, code]
    assert merge([chrome, code], [chrome], "remove") == [code]
    assert WorkflowStep.from_dict(chrome.to_dict()) == chrome


# ------------------------------------------------------------------ history (unit)


def test_history_periods_terms_and_outcomes():
    now = datetime(2026, 10, 2, 15, 30)
    assert period_range("today", now) == (datetime(2026, 10, 2), None)
    assert period_range("yesterday", now) == (datetime(2026, 10, 1), datetime(2026, 10, 2))
    assert period_range("week", now)[0] == now - timedelta(days=7)
    assert period_range("", now) == (None, None)
    assert search_terms("kal maine report ke baare mein kya kaha tha") == ["report"]
    convo = {"status": "understood"}
    assert outcome(convo, [{"execution_status": "success", "verification_status": "passed"}]) == "done"
    assert outcome(convo, [{"execution_status": "success", "verification_status": "failed"}]) == "failed"
    assert outcome(convo, [{"execution_status": "not_executed_denied", "verification_status": "not_applicable"}]) == "denied"
    assert outcome(convo, [{"execution_status": "responded", "verification_status": "not_applicable"}]) == "answered"


# ------------------------------------------------------------------ understanding


@pytest.mark.parametrize("text,name,entities", [
    ("yaad rakho ke meri wife ki birthday 5 March ko hai", "remember_fact",
     {"fact": "meri wife ki birthday 5 March ko hai", "explicit": True}),
    ("kal 5 baje meeting hai, ye yaad rakhna", "remember_fact", {"fact": "kal 5 baje meeting hai", "explicit": True}),
    ("ye yaad rakho", "remember_fact", {"fact": "", "explicit": True}),
    ("mera naam Ahmed hai", "remember_fact", {"fact": "mera naam Ahmed hai", "explicit": False}),
    ("mera naam kya hai", "recall_memory", {"query": "naam"}),
    ("tumhe mere baare mein kya yaad hai", "recall_memory", {"query": ""}),
    ("what do you remember about me", "recall_memory", {"query": ""}),
    ("chai wali baat bhool jao", "forget_memory", {"query": "chai"}),
    ("sab kuch bhool jao", "forget_memory", {"all": True}),
    ("naya topic", "forget_memory", {"scope": "conversation"}),
    ("kal maine kya kaha tha", "search_history", {"query": "", "period": "yesterday"}),
    ("aaj kya kya kiya", "search_history", {"query": "", "period": "today"}),
    ("history mein report dhoondo", "search_history", {"query": "report", "period": ""}),
    ("aaj ki history mita do", "clear_history", {"period": "today"}),
    ("saari history delete karo", "clear_history", {"period": ""}),
    ("work start karo", "run_workflow", {"workflow": "work"}),
    ("study workflow chalao", "run_workflow", {"workflow": "study"}),
    ("study workflow banao: YouTube aur Notion", "save_workflow",
     {"workflow": "study", "steps": "YouTube aur Notion", "edit_action": "replace"}),
    ("work workflow mein Spotify bhi add karo", "save_workflow",
     {"workflow": "work", "steps": "Spotify", "edit_action": "add"}),
    ("work workflow se WhatsApp hata do", "save_workflow",
     {"workflow": "work", "steps": "WhatsApp", "edit_action": "remove"}),
    ("mere workflows dikhao", "list_workflows", {}),
    ("study workflow delete karo", "delete_workflow", {"workflow": "study"}),
    ("dobara karo", "repeat_last", {"what": "command"}),
    ("kya kaha", "repeat_last", {"what": "response"}),
])
def test_rules_understand_memory_commands(text, name, entities):
    u = arun(RuleBasedProvider().understand(text))
    assert [(i.name, i.entities) for i in u.intents] == [(name, entities)]
    assert u.intents[0].confidence >= 0.8


@pytest.mark.parametrize("text,name", [("system dobara scan karo", "rescan_system"),
                                       ("likho: kal meeting hai yaad rakhna", "type_text"),
                                       ("Chrome kholo", "open_app")])
def test_memory_rules_do_not_steal_other_commands(text, name):
    assert arun(RuleBasedProvider().understand(text)).intents[0].name == name


def test_model_output_for_memory_intents():
    def parse(item, text):
        return parse_model_output(json.dumps({"intents": [item], "answer": ""}), "roman_urdu", "ollama", text)[0][0]

    # The model may call a plain statement "explicit"; only the user's own "yaad rakho" makes it so.
    assert parse({"name": "remember_fact", "fact": "mera laptop slow hai", "explicit": True},
                 "mera laptop slow hai").entities == {"fact": "mera laptop slow hai", "explicit": False}
    assert parse({"name": "remember_fact", "fact": "Ali ki shaadi 5 ko hai", "explicit": True},
                 "yaad rakho ke Ali ki shaadi 5 ko hai").entities["explicit"] is True
    assert parse({"name": "search_history", "query": "files delete", "period": "week"}, "x").entities == {
        "query": "files delete", "period": "week"}
    assert parse({"name": "search_history", "period": "someday"}, "x").entities == {}
    assert parse({"name": "forget_memory", "all": True}, "x").entities == {"all": True}
    assert parse({"name": "save_workflow", "workflow": "study workflow", "steps": "YouTube"}, "x").entities == {
        "workflow": "study", "steps": "YouTube", "edit_action": "replace"}
    # Regression (Phase 8C): the app of a window action from the model was dropped.
    assert parse({"name": "window_control", "window_action": "maximize", "app": "Chrome"}, "x").entities == {
        "action": "maximize", "app": "Chrome"}
    props = _schema()["properties"]["intents"]["items"]["properties"]
    assert props["name"]["enum"] == list(KNOWN_INTENTS)  # a new field must never replace the intent list


# ------------------------------------------------------------------ long-term memory through NOVA


def test_explicit_remember_is_saved_and_verified(env):
    body = cmd(env.client, "yaad rakho ke meri wife ki birthday 5 March ko hai")
    assert "Yaad kar liya" in body["response"] and "Verify" in body["response"]
    assert facts(env.client) == ["meri wife ki birthday 5 March ko hai"]
    assert env.client.get("/api/activity?limit=1").json()[0]["verification_status"] == "passed"
    assert events(env.client, "MEMORY_CHANGED")
    assert "5 March" in cmd(env.client, "yaad hai ke meri biwi ki salgirah kab hai")["response"]
    assert "pehle se yaad" in cmd(env.client, "yaad rakho ke meri wife ki birthday 5 March ko hai")["response"]


def test_personal_statement_is_only_saved_after_haan(env):
    c = env.client
    body = cmd(c, "mera naam Ahmed hai")
    assert "Kya main aap ka naam yaad rakhoon" in body["response"] and facts(c) == []
    reply = events(c, "NOVA_RESPONSE")[-1].data
    assert reply["awaiting_answer"] is True and reply["quick_replies"] == ["Haan", "Nahi"]
    body = cmd(c, "haan")
    assert "Yaad kar liya" in body["response"] and "Ahmed kahunga" in body["response"]
    assert events(c, "NOVA_RESPONSE")[-1].data["awaiting_answer"] is False
    assert cmd(c, "mera naam kya hai")["response"] == "Aap ka naam Ahmed hai."
    assert cmd(c, "salam")["response"].startswith("Assalam-o-Alaikum Ahmed!")
    # A new name replaces the old one (one name), and the user is told.
    body = cmd(c, "yaad rakho ke mera naam Ali hai")
    assert "Pehle wali baat" in body["response"] and facts(c) == ["mera naam Ali hai"]


def test_nahi_is_respected_and_not_asked_again(env):
    c = env.client
    cmd(c, "mujhe chai pasand hai")
    assert cmd(c, "nahi")["response"] == "Theek hai, ye baat yaad nahi rakhi."
    assert facts(c) == []
    assert cmd(c, "mujhe chai pasand hai")["response"] == "Achha, samajh gaya."  # not asked twice this session
    history = c.get("/api/history?q=nahi").json()
    assert history and history[0]["intent"] == "followup"


def test_a_new_command_instead_of_an_answer_drops_the_question(env):
    c = env.client
    cmd(c, "mujhe chai pasand hai")
    body = cmd(c, "RAM batao")
    assert body["executed"] and "RAM" in body["response"]
    assert cmd(c, "haan")["status"] != "permission_answer" and facts(c) == []


def test_secrets_and_reminders_are_refused(env):
    c = env.client
    body = cmd(c, "yaad rakho ke mera ATM pin 4321 hai")
    assert "yaad nahi rakhta" in body["response"] and facts(c) == []
    assert c.get("/api/activity?limit=1").json()[0]["permission_status"] == "refused_by_nova"
    assert "reminder" in cmd(c, "yaad rakho ke kal 5 baje yaad dilana")["response"]


def test_ye_yaad_rakho_means_what_was_just_said(env):
    c = env.client
    cmd(c, "kal 5 baje dentist ke paas jana hai")
    cmd(c, "ye yaad rakho")
    assert facts(c) == ["kal 5 baje dentist ke paas jana hai"]
    assert cmd(c, "ye yaad rakho")["response"].startswith("Ye mujhe pehle se yaad hai")


def test_forgetting_is_asked_first_and_never_remembered(env):
    c = env.client
    cmd(c, "yaad rakho ke mujhe chai pasand hai")
    cmd(c, "yaad rakho ke Ali ki shaadi December mein hai")
    t, results, req = ask(c, "chai wali baat bhool jao")
    item = req["items"][0]
    assert req["max_risk"] == "medium" and not req["rememberable"] and "- mujhe chai pasand hai" in item["preview"]
    decide(c, req, False)
    t.join()
    assert "mujhe chai pasand hai" in facts(c)
    t, results, req = ask(c, "chai wali baat bhool jao")
    decide(c, req, True)
    t.join()
    assert "bhool gaya" in results[0]["response"] and facts(c) == ["Ali ki shaadi December mein hai"]
    t, results, req = ask(c, "sab kuch bhool jao")
    assert req["max_risk"] == "high"
    decide(c, req, True)
    t.join()
    assert facts(c) == []
    assert "kuch yaad hi nahi" in cmd(c, "Ali wali baat bhool jao")["response"]


def test_recall_lists_everything_or_says_nothing_is_known(env):
    c = env.client
    assert "kuch yaad nahi" in cmd(c, "tumhe kya yaad hai")["response"]
    cmd(c, "yaad rakho ke mujhe chai pasand hai")
    cmd(c, "yaad rakho ke main Lahore mein rehta hoon")
    body = cmd(c, "tumhe mere baare mein kya yaad hai")
    assert "(2)" in body["response"] and "Lahore" in body["response"] and "chai" in body["response"]
    assert "Lahore" in cmd(c, "main kahan rehta hoon")["response"]


def test_naya_topic_clears_short_term_memory_only(env):
    c = env.client
    cmd(c, "yaad rakho ke mujhe chai pasand hai")
    cmd(c, "RAM batao")
    assert c.get("/api/memory/short-term").json()["turns"]
    cmd(c, "naya topic")
    snap = c.get("/api/memory/short-term").json()
    assert [t["user"] for t in snap["turns"]] == ["naya topic"] and facts(c) == ["mujhe chai pasand hai"]


# ------------------------------------------------------------------ history


def test_history_search_and_records(env):
    c = env.client
    cmd(c, "RAM batao")
    cmd(c, "Chrome kholo")
    body = cmd(c, "aaj kya kya kiya")
    assert "Aaj ki history" in body["response"] and "“RAM batao”" in body["response"]
    assert "“Chrome kholo”" in body["response"] and "(ho gaya)" in body["response"]
    body = cmd(c, "history mein RAM dhoondo")
    assert "RAM batao" in body["response"] and "Chrome kholo" not in body["response"]
    assert "kuch nahi mila" in cmd(c, "kal maine kya kaha tha")["response"]
    records = c.get("/api/history").json()
    chrome = next(r for r in records if r["request"] == "Chrome kholo")
    assert chrome["outcome"] == "done" and chrome["verification"] == "passed" and chrome["actions"]
    assert {"date", "time", "request", "response", "permission", "error", "outcome"} <= set(chrome)
    assert [r["request"] for r in c.get("/api/history?q=chrome").json()] == ["Chrome kholo"]
    assert c.get("/api/history?period=someday").status_code == 422


def test_clearing_history_is_high_risk_and_complete(env):
    c = env.client
    cmd(c, "RAM batao")
    t, results, req = ask(c, "saari history mita do")
    assert req["max_risk"] == "high" and not req["rememberable"]
    assert "baatein:" in req["items"][0]["preview"] and "activity log" in req["items"][0]["preview"]
    decide(c, req, False)
    t.join()
    assert any(r["request"] == "RAM batao" for r in c.get("/api/history").json())
    t, results, req = ask(c, "saari history mita do")
    decide(c, req, True)
    t.join()
    assert "History mita di" in results[0]["response"]
    requests = [r["request"] for r in c.get("/api/history").json()]
    assert "RAM batao" not in requests and requests == ["saari history mita do"]  # only this command's own record
    assert not any(e.data.get("text") == "RAM batao" for e in c.app.state.bus.history())
    assert c.get("/api/memory/short-term").json()["turns"] == [
        {"user": "saari history mita do", "assistant": results[0]["response"][:500]}]


def test_old_history_is_deleted_after_the_chosen_days(env):
    c = env.client
    db = c.app.state.db
    old = (datetime.now() - timedelta(days=100)).isoformat(timespec="seconds")
    db._execute("INSERT INTO conversations(task_id, created_at, source, user_text, response, status) "
                "VALUES ('old1', ?, 'text', 'purani baat', 'jawab', 'understood')", (old,))
    db._execute("INSERT INTO activity_log(date, time, task_id, task_name, agent, action, permission_status, "
                "execution_status, test_status, verification_status, admin_status) VALUES (?, '10:00:00', 'old1', "
                "'command:chat', 'Orchestrator', 'respond', 'not_required', 'responded', 'not_run', "
                "'not_applicable', 'pending')", (old[:10],))
    cmd(c, "RAM batao")
    assert c.app.state.orchestrator.purge_history(force=True) == 1
    assert c.get("/api/history?q=purani").json() == [] and db.activity_for_tasks(["old1"])["old1"] == []
    assert c.get("/api/history?q=RAM").json()  # recent history stays
    db._execute("INSERT INTO conversations(task_id, created_at, source, user_text, response, status) "
                "VALUES ('old2', ?, 'text', 'purani baat', 'jawab', 'understood')", (old,))
    assert c.put("/api/settings", json={"history_days": 0}).json()["history_days"] == 0
    assert c.app.state.orchestrator.purge_history(force=True) == 0  # 0 = keep everything
    assert c.put("/api/settings", json={"history_days": 45}).status_code == 422
    c.put("/api/settings", json={"history_days": 30})  # a shorter period applies right away
    assert c.get("/api/history?q=purani").json() == []


# ------------------------------------------------------------------ workflows through NOVA


def test_first_work_start_asks_then_remembers_and_runs(env):
    c = env.client
    body = cmd(c, "work start karo")
    assert "Kaun se applications open karoon" in body["response"]
    assert events(c, "NOVA_RESPONSE")[-1].data["awaiting_answer"] is True
    body = cmd(c, "Chrome, VS Code aur example.com")
    assert "'work' workflow save ho gaya" in body["response"] and body["executed"]
    launched = [call[1] for call in env.desktop.calls if call[0] == "launch"]
    assert launched == ["Google Chrome", "Visual Studio Code"]
    assert ("goto", "https://example.com") in env.browser.calls or any(
        call[0] == "goto" and "example.com" in call[1] for call in env.browser.calls)
    saved = c.get("/api/workflows").json()
    assert saved[0]["name"] == "work" and [s["label"] for s in saved[0]["steps"]] == [
        "Google Chrome", "Visual Studio Code", "example.com"]
    # Later: runs straight away, nothing asked (only "open" steps).
    env.desktop.calls.clear()
    t, results, req = ask(c, "work start karo")
    t.join()
    assert req is None and results[0]["response"].startswith("'work' workflow (3 cheezein):")
    assert [call[1] for call in env.desktop.calls if call[0] == "launch"] == ["Google Chrome", "Visual Studio Code"]
    assert c.get("/api/workflows").json()[0]["runs"] == 2  # the first time counts too
    assert "dobara" not in results[0]["response"]
    body = cmd(c, "dobara karo")  # repeating a workflow runs the workflow again (not "save nahi")
    assert body["response"].startswith("'work' workflow (3 cheezein):")
    assert c.get("/api/workflows").json()[0]["runs"] == 3


def test_workflow_answer_that_is_a_new_command_is_not_saved(env):
    c = env.client
    cmd(c, "work start karo")
    body = cmd(c, "RAM batao")
    assert "RAM" in body["response"] and c.get("/api/workflows").json() == []
    assert "Theek hai, workflow nahi banaya" in (cmd(c, "work start karo") and cmd(c, "rehne do"))["response"]


def test_workflow_with_unknown_items_asks_again_once(env):
    c = env.client
    cmd(c, "work start karo")
    body = cmd(c, "FooApp aur BarApp")
    assert "In mein se kuch nahi mila" in body["response"]
    body = cmd(c, "Chrome aur FooApp")
    assert "save ho gaya" in body["response"] and "Ye nahi daal saka" in body["response"]
    assert [s["label"] for s in c.get("/api/workflows").json()[0]["steps"]] == ["Google Chrome"]


def test_named_workflows_edit_list_run_and_delete(env):
    c = env.client
    folder = env.root / "home" / "Downloads"
    body = cmd(c, "study workflow banao: example.com, Downloads folder aur volume 30")
    assert "'study' workflow save ho gaya (3 cheezein)" in body["response"]
    cmd(c, "study workflow mein Photoshop bhi add karo")
    cmd(c, "study workflow se example.com hata do")
    steps = [s["label"] for s in c.get("/api/workflows").json()[0]["steps"]]
    assert steps == ["Downloads", "Volume 30%", "Adobe Photoshop CC 2019"]
    assert "study: Downloads, Volume 30%, Adobe Photoshop CC 2019" in cmd(c, "mere workflows dikhao")["response"]
    body = cmd(c, "study start karo")  # an app name that is a saved workflow runs the workflow
    assert body["response"].startswith("'study' workflow (3 cheezein):")
    assert env.opened == [folder] and env.settings.state["volume"] == 30
    t, results, req = ask(c, "study workflow delete karo")
    assert req["max_risk"] == "medium" and not req["rememberable"] and "Downloads" in req["items"][0]["preview"]
    decide(c, req, True)
    t.join()
    assert c.get("/api/workflows").json() == []


def test_repeat_last_command_and_last_reply(env):
    c = env.client
    assert "koi pichla kaam yaad nahi" in cmd(c, "dobara karo")["response"]
    first = cmd(c, "Chrome kholo")
    env.desktop.calls.clear()
    again = cmd(c, "dobara karo")
    assert [call for call in env.desktop.calls if call[0] == "launch"] and again["intents"][0]["name"] == "open_app"
    assert cmd(c, "kya kaha")["response"] == again["response"]
    cmd(c, "dobara karo")  # still the original command, not "dobara karo" itself
    assert len([call for call in env.desktop.calls if call[0] == "launch"]) == 2
    assert first["response"]
    cmd(c, "mujhe chai pasand hai")  # a statement (and its answer) is not a command to repeat
    cmd(c, "nahi")
    cmd(c, "dobara karo")
    assert len([call for call in env.desktop.calls if call[0] == "launch"]) == 3


# ------------------------------------------------------------------ API (Memory tab)


def test_memory_api(env):
    c = env.client
    row = c.post("/api/memory/facts", json={"text": "mera naam Ahmed hai"}).json()
    assert row["slot"] == "name" and row["value"] == "Ahmed" and row["source"] == "user_ui"
    r = c.post("/api/memory/facts", json={"text": "mera password hunter2 hai"})
    assert r.status_code == 422 and "hunter2" not in r.text  # the secret is never echoed back
    assert c.post("/api/memory/facts", json={"text": "mera naam Ahmed hai"}).status_code == 422
    c.post("/api/memory/facts", json={"text": "mujhe chai pasand hai"})
    assert c.delete(f"/api/memory/facts/{row['id']}").json() == {"ok": True}
    assert c.delete(f"/api/memory/facts/{row['id']}").status_code == 404
    assert c.delete("/api/memory/facts").json()["removed"] == 1 and facts(c) == []

    saved = c.put("/api/workflows", json={"name": "Work", "steps": "Chrome, WhatsApp, FooApp"}).json()
    assert saved["workflow"]["name"] == "work" and saved["problems"] and "1. Google Chrome (app)" in saved["summary"]
    assert c.put("/api/workflows", json={"name": "x", "steps": "FooApp"}).status_code == 422
    assert c.delete(f"/api/workflows/{saved['workflow']['id']}").json() == {"ok": True}
    actions = [a["action"] for a in c.get("/api/activity?limit=50").json()]
    assert {"remember_fact", "forget_memory", "save_workflow", "delete_workflow"} <= set(actions)

    cmd(c, "RAM batao")
    task = c.get("/api/history?q=RAM").json()[0]["task_id"]
    assert c.delete(f"/api/history/{task}").json() == {"ok": True}
    assert c.get("/api/history?q=RAM").json() == []
    cmd(c, "Chrome kholo")
    assert c.get("/api/memory/short-term").json()["last_command"] == "Chrome kholo"
    assert c.delete("/api/history").json()["removed"] >= 1 and c.get("/api/history").json() == []
    assert c.get("/api/memory/short-term").json()["turns"] == []
    cmd(c, "RAM batao")
    assert c.delete("/api/memory/short-term").json() == {"ok": True}
    assert c.get("/api/memory/short-term").json()["last_command"] is None
    assert "clear_history" in [a["action"] for a in c.get("/api/activity?limit=50").json()]  # the deletion is logged


# ------------------------------------------------------------------ the AI brain uses related memories


def test_related_memories_reach_the_local_model_only_when_relevant(tmp_path):
    ollama = FakeOllama(models=["qwen3:4b"])
    ollama.reply = lambda text: {"intents": [{"name": "chat"}], "answer": "Biryani bana lein."}
    with build_client(tmp_path, ollama) as c:
        c.post("/api/memory/facts", json={"text": "mujhe biryani bohat pasand hai"})
        c.post("/api/memory/facts", json={"text": "Ali ki shaadi December mein hai"})
        cmd(c, "aaj dinner mein kya banaun jo mujhe pasand ho")
        prompt = ollama.chat_requests[-1]["messages"][-1]["content"]
        assert "Things the user asked NOVA to remember" in prompt and "biryani" in prompt and "shaadi" not in prompt
        assert prompt.rstrip().endswith("CURRENT message: aaj dinner mein kya banaun jo mujhe pasand ho")
        cmd(c, "quantum physics kya hoti hai")
        prompt = ollama.chat_requests[-1]["messages"][-1]["content"]
        assert "remember" not in prompt
        # Earlier turns go along shortened: long replies would make a CPU model slow (live test finding).
        assert "Recent conversation" in prompt and len(prompt) < 900


def test_files_root_isolated(tmp_path):
    # The Memory Agent never writes outside NOVA's database: no files appear in the user's folders.
    with build_client(tmp_path) as c:
        cmd(c, "yaad rakho ke mujhe chai pasand hai")
        cmd(c, "study workflow banao: example.com")
    assert not any(p.is_file() for p in Path(files_root(tmp_path)).rglob("*"))
