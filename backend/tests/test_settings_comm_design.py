"""Phase 8C: Windows settings, Communication Agent (WhatsApp/email to saved contacts), Design Agent (image tools)."""

import asyncio
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from conftest import (FakeDesign, FakeDesktop, FakeMailer, FakeOllama, FakeSettings, FakeWhatsApp, build_client,
                      files_root)
from nova.agents.settings_agent import parse_level
from nova.ai.ollama import _schema, parse_model_output
from nova.ai.rule_based import RuleBasedProvider
from nova.communication.contacts import Contact, find_contact, normalize_phone, show_phone, valid_email
from nova.communication.whatsapp import WhatsAppDesktop, click_to_chat_url
from nova.control.windows import WindowInfo
from nova.design import images as im
from nova.design.agent import parse_operation


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


def last_activity(client):
    return client.get("/api/activity?limit=1").json()[0]


@pytest.fixture
def env(tmp_path):
    fakes = SimpleNamespace(settings=FakeSettings(), whatsapp=FakeWhatsApp(), mailer=FakeMailer(), design=FakeDesign())
    with build_client(tmp_path, desktop=FakeDesktop(), permission_timeout_s=10, settings=fakes.settings,
                      whatsapp=fakes.whatsapp, mailer=fakes.mailer, design=fakes.design) as client:
        fakes.client = client
        fakes.home = files_root(tmp_path) / "home"
        yield fakes


# ------------------------------------------------------------------ settings


@pytest.mark.parametrize("text,current,step,expected", [
    ("50", 78, 10, 50), ("50%", 78, 10, 50), ("kam", 78, 10, 68), ("bohat kam", 78, 10, 58), ("zyada", 95, 10, 100),
    ("aadha", 10, 10, 50), ("full", 10, 10, 100), ("kaisa hai", 50, 10, None),
])
def test_level_words(text, current, step, expected):
    assert parse_level(text, current, step) == expected


def test_volume_and_brightness_change_without_asking_and_are_verified(env):
    body = cmd(env.client, "volume 25 kar do")
    assert body["executed"] and "Volume 25% kar diya" in body["response"] and env.settings.state["volume"] == 25
    assert last_activity(env.client)["verification_status"] == "passed"
    cmd(env.client, "awaaz thori kam karo")
    assert env.settings.state["volume"] == 15
    cmd(env.client, "awaaz band karo")
    assert env.settings.state["muted"] is True
    assert "pehle se band" in cmd(env.client, "mute karo")["response"]
    cmd(env.client, "brightness 40 karo")
    assert env.settings.state["brightness"] == 40


def test_dark_mode_and_turning_off_wifi_ask_first(env):
    t, results, req = ask(env.client, "dark mode on karo")
    assert req["max_risk"] == "medium" and "dark mode" in req["question"]
    decide(env.client, req, True)
    t.join()
    assert env.settings.state["theme"] == "dark" and "Verify" in results[0]["response"]
    t, results, req = ask(env.client, "wifi band karo")
    assert "Internet band ho jayega" in req["question"]
    decide(env.client, req, False)
    t.join()
    assert env.settings.state["wifi"] == "on"  # denied: untouched
    assert "pehle se on" in cmd(env.client, "bluetooth on kar do")["response"]


def test_security_settings_are_refused_and_default_browser_opens_settings(env):
    body = cmd(env.client, "firewall band karo")
    assert "kabhi nahi badalta" in body["response"] and not env.settings.calls
    assert last_activity(env.client)["permission_status"] == "refused_by_nova"
    body = cmd(env.client, "Chrome ko default browser bana do")
    assert env.settings.pages == ["ms-settings:defaultapps"] and "khud badalne nahi deta" in body["response"]
    cmd(env.client, "display settings kholo")
    assert env.settings.pages[-1] == "ms-settings:display"


# ------------------------------------------------------------------ contacts


def test_phone_numbers_and_emails():
    assert normalize_phone("0300 1234567") == "923001234567"
    assert normalize_phone("+92-300-1234567") == "923001234567"
    assert normalize_phone("00971501234567") == "971501234567"
    assert normalize_phone("12345") is None
    assert show_phone("923001234567") == "+92 300 1234567"
    assert valid_email("Ali@Example.com") == "ali@example.com" and valid_email("ali@") is None
    people = [Contact("Ali Khan"), Contact("Ali Raza"), Contact("Sara")]
    assert isinstance(find_contact("ali", people), list) and find_contact("sara", people).name == "Sara"
    assert find_contact("ali raza", people).name == "Ali Raza" and find_contact("bilal", people) is None


def test_contacts_by_command_and_api(env):
    body = cmd(env.client, "Ali ka number 0300 1234567 save karo")
    assert "+92 300 1234567" in body["response"] and body["executed"]
    cmd(env.client, "Ali ka email ali@example.com save karo")
    rows = env.client.get("/api/contacts").json()
    assert len(rows) == 1 and rows[0]["phone"] == "923001234567" and rows[0]["email"] == "ali@example.com"
    r = env.client.post("/api/contacts", json={"name": "Sara", "phone": "12"})
    assert r.status_code == 422 and "Number sahi nahi" in r.text
    assert env.client.post("/api/contacts", json={"name": "Sara", "phone": "+923211234567"}).status_code == 200
    assert "2 contacts" in cmd(env.client, "mere contacts dikhao")["response"]
    sara = next(c for c in env.client.get("/api/contacts").json() if c["name"] == "Sara")
    assert env.client.delete(f"/api/contacts/{sara['id']}").json() == {"ok": True}


# ------------------------------------------------------------------ messages


def test_whatsapp_send_shows_recipient_and_text_asks_every_time_and_verifies(env):
    cmd(env.client, "Ali ka number 0300 1234567 save karo")
    t, results, req = ask(env.client, "Ali ko WhatsApp par message bhejo ke kal meeting 5 baje hai aur chai lana")
    item = req["items"][0]
    assert item["preview"] == "WhatsApp → Ali (+92 300 1234567)\n\nkal meeting 5 baje hai aur chai lana"
    assert req["max_risk"] == "medium" and item["rememberable"] is False
    decide(env.client, req, True)
    t.join()
    assert env.whatsapp.sent == [("923001234567", "kal meeting 5 baje hai aur chai lana")]
    assert "bhej diya" in results[0]["response"] and last_activity(env.client)["verification_status"] == "passed"


def test_message_is_not_sent_when_whatsapp_cannot_be_confirmed(env):
    cmd(env.client, "Ali ka number 03001234567 save karo")
    env.whatsapp.composer_ok = False
    t, results, req = ask(env.client, "Ali ko message bhejo ke salam")
    decide(env.client, req, True)
    t.join()
    assert env.whatsapp.opened and not env.whatsapp.sent and "kuch nahi bheja" in results[0]["response"]


def test_denied_message_is_never_opened(env):
    cmd(env.client, "Ali ka number 03001234567 save karo")
    t, results, req = ask(env.client, "Ali ko message bhejo ke salam")
    decide(env.client, req, False)
    t.join()
    assert not env.whatsapp.opened and not env.whatsapp.sent


def test_unknown_recipient_is_not_searched_for(env):
    body = cmd(env.client, "Bilal ko message bhejo ke salam")
    assert "contacts mein nahi" in body["response"] and "khud nahi dhoondta" in body["response"]
    assert not env.whatsapp.opened


def test_typed_number_works_without_a_contact(env):
    t, results, req = ask(env.client, "03001234567 ko message bhejo ke test")
    assert "+92 300 1234567" in req["items"][0]["preview"]
    decide(env.client, req, False)
    t.join()


def test_password_in_a_message_is_high_risk(env):
    cmd(env.client, "Ali ka number 03001234567 save karo")
    t, results, req = ask(env.client, "Ali ko message bhejo ke mera password abc123 hai")
    assert req["max_risk"] == "high"
    decide(env.client, req, False)
    t.join()


def test_draft_is_prepared_by_the_model_and_not_sent(tmp_path):
    ollama = FakeOllama(models=["qwen3:4b"])
    ollama.reply = lambda text: {"message": "Salam Ali, maazrat, main aaj nahi aa sakunga."} if "REQUEST:" in text \
        else {"intents": [{"name": "unknown"}], "answer": ""}
    whatsapp = FakeWhatsApp()
    with build_client(tmp_path, ollama, whatsapp=whatsapp) as client:
        cmd(client, "Ali ka number 03001234567 save karo")
        body = cmd(client, "Ali ke liye message prepare karo ke main aaj nahi aa sakta")
    assert whatsapp.opened == [("923001234567", "Salam Ali, maazrat, main aaj nahi aa sakunga.")]
    assert not whatsapp.sent and "bheja nahi" in body["response"]


def test_email_with_outlook_and_without(env, tmp_path):
    cmd(env.client, "Ahmed ka email ahmed@example.com save karo")
    t, results, req = ask(env.client, "Ahmed ko email karo ke report tayyar hai")
    assert "Subject: report tayyar hai" in req["items"][0]["preview"]
    decide(env.client, req, True)
    t.join()
    assert env.mailer.sent == [("ahmed@example.com", "report tayyar hai", "report tayyar hai", [])]
    assert "Sent Items" in results[0]["response"]
    env.mailer.ready = False  # no Outlook account: a draft in the mail app, the user sends
    body = cmd(env.client, "Ahmed ko email karo ke kal milte hain")
    assert env.mailer.mailto and "Send aap khud" in body["response"]


def test_email_attachment_from_the_allowed_folders(env):
    (env.home / "Documents" / "report.pdf").write_bytes(b"%PDF-1.4 test")
    cmd(env.client, "Ahmed ka email ahmed@example.com save karo")
    t, results, req = ask(env.client, "report.pdf Ahmed ko email kar do")
    assert "Attachment: report.pdf" in req["items"][0]["preview"] and "bahar jayegi" in req["question"]
    decide(env.client, req, True)
    t.join()
    assert env.mailer.sent[0][3] == ["report.pdf"]


def test_whatsapp_driver_only_presses_enter_in_whatsapp():
    pressed, focused = [], []
    window = WindowInfo(hwnd=5, title="WhatsApp", pid=1, process="WhatsApp.Root.exe", class_name="x",
                        minimized=False, maximized=False)
    wa = WhatsAppDesktop(lambda: [window], lambda h: focused.append(h) or True, lambda: 99,
                         lambda: pressed.append(1) or True, opener=lambda url: None, focused_value=lambda: None,
                         capture=lambda h: None, ocr=lambda img: [], wait_s=0.1, settle_s=0)
    assert wa.press_send(window) is False and not pressed  # another window stayed in front: nothing pressed
    assert click_to_chat_url("923001234567", "kal 5 baje & chai?") == \
        "whatsapp://send?phone=923001234567&text=kal%205%20baje%20%26%20chai%3F"


def test_whatsapp_driver_reads_the_message_box():
    window = WindowInfo(hwnd=5, title="WhatsApp", pid=1, process="WhatsApp.Root.exe", class_name="x",
                        minimized=False, maximized=False)
    box = {"value": "kal meeting 5 baje hai"}
    wa = WhatsAppDesktop(lambda: [window], lambda h: True, lambda: 5, lambda: True, opener=lambda url: None,
                         focused_value=lambda: box["value"], capture=lambda h: None, ocr=lambda img: [],
                         wait_s=0.1, settle_s=0)
    assert wa.composer_holds(window, "Kal meeting 5 baje hai!") is True
    box["value"] = "kuch aur"
    assert wa.composer_holds(window, "kal meeting 5 baje hai") is False


# ------------------------------------------------------------------ design


@pytest.mark.parametrize("words,expected", [
    ("1080x1080", ("fit", (1080, 1080))), ("instagram post size ka", ("fit", (1080, 1080))),
    ("png mein", ("convert", "png")), ("compress", ("compress", 75)), ("90 degree", ("rotate", 90)),
    ("black and white", ("grayscale", True)), ("'KN Softic' watermark lagao", ("watermark", "KN Softic")),
    ("'Eid Mubarak' likho", ("caption", "Eid Mubarak")), ("50% chhota", ("resize", 50)), ("kuch bhi", None),
])
def test_image_operation_words(words, expected):
    assert parse_operation(words) == expected


def make_photo(path: Path, size=(1600, 1200)) -> Path:
    Image.new("RGB", size, (30, 120, 200)).save(path, "JPEG")
    return path


@pytest.mark.parametrize("text,suffix,size", [
    ("photo.jpg ko 1080x1080 kar do", "-1080x1080.jpg", (1080, 1080)),
    ("photo.jpg ko png mein badal do", "-png.png", (1600, 1200)),
    ("photo.jpg ko 90 degree ghumao", "-rotated-90.jpg", (1200, 1600)),
    ("photo.jpg ko 50% chhota kar do", "-50%.jpg", (800, 600)),
    ("photo.jpg par 'KN Softic' watermark lagao", "-watermark.jpg", (1600, 1200)),
])
def test_image_edits_make_a_new_verified_file(env, text, suffix, size):
    src = make_photo(env.home / "Pictures" / "photo.jpg")
    before = src.read_bytes()
    body = cmd(env.client, text)
    out = env.home / "Pictures" / f"photo{suffix}"
    assert body["executed"] and out.exists(), body["response"]
    with Image.open(out) as img:
        assert img.size == size
    assert src.read_bytes() == before  # the original is untouched
    assert last_activity(env.client)["verification_status"] == "passed"


def test_create_design_and_open_with_app(env):
    body = cmd(env.client, "Instagram post banao jis par 'Grand Sale 50% Off' likha ho")
    designs = list((env.home / "Pictures" / "NOVA" / "Designs").glob("*.png"))
    assert body["executed"] and len(designs) == 1 and env.design.opened == designs
    with Image.open(designs[0]) as img:
        assert img.size == (1080, 1080)
    body = cmd(env.client, "isko Photoshop mein kholo")  # "isko" = the design just made
    assert env.design.launched == [(r"C:\Apps\Photoshop.exe", designs[0])]
    assert "Photoshop" in body["response"]
    assert "Urdu script" in cmd(env.client, "post banao jis par 'عید مبارک' likha ho")["response"]
    assert "kya likhna hai" in cmd(env.client, "post banao")["response"]


def test_design_colours_and_text_fit():
    assert im.colors_from("neela aur sunehra") == (im.COLORS["neela"], im.COLORS["sunehra"])
    img = im.create_design((1280, 720), "A very long title that has to wrap onto more than one line to fit", "sub")
    assert img.size == (1280, 720)


# ------------------------------------------------------------------ brain


@pytest.mark.parametrize("text,name,entities", [
    ("volume 50 kar do", "change_setting", {"setting": "volume", "value": "50"}),
    ("awaaz band karo", "change_setting", {"setting": "mute"}),
    ("wifi band karo", "change_setting", {"setting": "wifi", "value": "band"}),
    ("dark mode on karo", "change_setting", {"setting": "theme"}),
    ("display settings kholo", "open_settings", {"page": "display"}),
    ("WhatsApp par Sara ko likho ke main late hoon", "send_message",
     {"recipient": "Sara", "channel": "whatsapp", "text": "main late hoon"}),
    ("Ali ka number 0300 1234567 save karo", "save_contact", {"name": "Ali", "phone": "0300 1234567"}),
    ("photo.jpg ko 1080x1080 kar do", "edit_image", {"target": "photo.jpg"}),
    ("'Eid Mubarak' ka sunehra poster banao", "create_design", {"kind": "poster", "text": "Eid Mubarak"}),
    ("photo.jpg ko Photoshop mein kholo", "open_with", {"app": "photoshop"}),
    # existing meanings stay
    ("Chrome band karo", "close_app", {"app": "Chrome"}),
    ("isko band kar do", "close_app", {}),
    ("copy karo", "keyboard_shortcut", {"keys": "copy"}),
])
def test_rules_understand_settings_messages_and_design(text, name, entities):
    intent = arun(RuleBasedProvider().understand(text)).intents[0]
    assert intent.name == name and {k: intent.entities.get(k) for k in entities} == entities


def test_model_schema_keeps_the_intent_list_and_reads_new_fields():
    props = _schema()["properties"]["intents"]["items"]["properties"]
    assert "enum" in props["name"] and "send_message" in props["name"]["enum"]  # a field named "name" must not clash
    raw = ('{"intents":[{"name":"send_message","channel":"whatsapp","recipient":"Ali","text":"  kal  5 baje ",'
           '"draft_only":true},{"name":"save_contact","contact_name":"Ali","phone":"03001234567"},'
           '{"name":"change_setting","setting":"nonsense","value":"50"}],"answer":""}')
    intents, _ = parse_model_output(raw, "roman_ur", "ollama:test")
    assert intents[0].entities == {"recipient": "Ali", "channel": "whatsapp", "text": "kal  5 baje", "draft_only": True}
    assert intents[1].entities == {"name": "Ali", "phone": "03001234567"}
    assert intents[2].entities == {"value": "50"}  # unknown setting dropped; the agent works it out from words
