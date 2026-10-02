"""Phase 8A: Browser Agent, Research Agent, safe fetching, search APIs, encrypted secrets."""

import asyncio
import threading
import time

import httpx
import pytest

from conftest import FakeBrowser, FakeDesktop, FakeOllama, FakeWeb, build_client, fake_resolver
from nova.control.windows import WindowInfo
from nova.research.extract import extract_text
from nova.research.netsafe import UnsafeUrlError, _pinned, check_url, fetch
from nova.research.search import BraveSearch, SearchError, WikipediaSearch


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ safe fetching (SSRF protection)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8765/api/health", "http://localhost:11434/", "http://10.0.0.5/", "http://192.168.1.1/",
    "http://172.16.0.1/", "http://169.254.169.254/latest/meta-data", "http://[::1]:8765/", "http://[::ffff:127.0.0.1]/",
    "http://0.0.0.0/", "file:///C:/Windows/win.ini", "ftp://example.com/", "javascript:alert(1)",
    "https://user:pass@example.com/", "http://evil.example/admin",  # evil.example resolves to 127.0.0.1
])
def test_unsafe_urls_are_blocked(url):
    with pytest.raises(UnsafeUrlError):
        run(check_url(url, fake_resolver))


def test_public_url_allowed_and_connection_pinned_to_checked_ip():
    assert run(check_url("https://example.com/page", fake_resolver)) == ["93.184.216.34"]
    pinned, headers, ext = _pinned("https://example.com:8443/a?b=1", "93.184.216.34")
    assert pinned == "https://93.184.216.34:8443/a?b=1"
    assert headers == {"Host": "example.com:8443"} and ext == {"sni_hostname": "example.com"}
    assert _pinned("http://example.com/", "2606:2800::1")[0] == "http://[2606:2800::1]/"


def test_redirect_into_local_network_is_blocked():
    def handler(request):
        return httpx.Response(302, headers={"location": "http://evil.example/admin"})

    with pytest.raises(UnsafeUrlError):
        run(fetch("https://example.com/", httpx.MockTransport(handler), fake_resolver))


def test_non_html_and_oversized_responses():
    def binary(request):
        return httpx.Response(200, content=b"MZ", headers={"content-type": "application/octet-stream"})

    with pytest.raises(UnsafeUrlError):
        run(fetch("https://example.com/x.exe", httpx.MockTransport(binary), fake_resolver))

    def huge(request):
        return httpx.Response(200, content=b"a" * 3_000_000, headers={"content-type": "text/plain"})

    page = run(fetch("https://example.com/big", httpx.MockTransport(huge), fake_resolver))
    assert len(page.text) == 2_000_000


def test_extract_text_prefers_article_and_clips():
    html = "<html><head><title>T</title></head><body><nav>menu menu</nav><article><p>" + "word " * 2000 + \
           "</p></article><script>var x=1</script></body></html>"
    title, text = extract_text(html, max_words=50)
    assert title == "T" and len(text.split()) <= 50 and "var x" not in text


# ------------------------------------------------------------------ search providers


def test_brave_search_parses_and_filters():
    web = FakeWeb()
    results = run(BraveSearch("KEY12345", web.transport).search("solar", 5))
    assert [r.url for r in results] == ["https://news.example.org/solar", "https://blog.example.net/solar",
                                        "http://evil.example/admin"]  # file:// dropped here; evil dropped on fetch
    assert web.brave_calls[0] == {"q": "solar", "key": "KEY12345"}
    assert results[0].extra == ["Capacity doubled."]


@pytest.mark.parametrize("status,message", [(401, "key sahi nahi"), (429, "had (quota)"), (500, "error diya")])
def test_brave_errors_are_explained(status, message):
    web = FakeWeb()
    web.brave_status = status
    with pytest.raises(SearchError, match=message.replace("(", r"\(").replace(")", r"\)")):
        run(BraveSearch("KEY12345", web.transport).search("x"))


def test_wikipedia_search():
    results = run(WikipediaSearch(FakeWeb().transport).search("capital of Pakistan"))
    assert results[0].title == "Islamabad" and "capital city of Pakistan" in results[0].snippet
    assert results[0].url == "https://en.wikipedia.org/wiki/Islamabad"
    assert len(results) == 1  # disambiguation / "may refer to:" list pages are not sources


# ------------------------------------------------------------------ secrets


def test_secret_is_encrypted_at_rest_and_never_returned(client):
    r = client.put("/api/secrets/brave_api_key", json={"value": "BSAabcdefgh12345XYZ9"})
    assert r.json() == {"ok": True, "masked": "••••XYZ9"}
    raw = client.app.state.db.get_setting("secret:brave_api_key")
    assert raw and "BSAabcdefgh12345XYZ9" not in raw  # DPAPI ciphertext, not the key
    status = client.get("/api/web/status").json()
    assert status["brave_configured"] and status["brave_key_masked"] == "••••XYZ9"
    assert "BSAabcdefgh12345XYZ9" not in str(status)
    assert "BSAabcdefgh12345XYZ9" not in str(client.get("/api/activity").json())
    client.delete("/api/secrets/brave_api_key")
    assert client.get("/api/web/status").json()["search_provider"] == "wikipedia"


def test_bad_secret_is_rejected_without_echo(client):
    r = client.put("/api/secrets/brave_api_key", json={"value": "bad key with spaces <script>"})
    assert r.status_code == 422 and "script" not in r.text
    assert client.put("/api/secrets/other", json={"value": "abcdefgh123"}).status_code == 404


# ------------------------------------------------------------------ browser agent through the API


@pytest.fixture
def setup(tmp_path):
    desktop, browser, web, ollama = FakeDesktop(), FakeBrowser(), FakeWeb(), FakeOllama(models=[])
    with build_client(tmp_path, ollama, desktop, permission_timeout_s=10, browser=browser, web=web) as client:
        yield client, desktop, browser, web, ollama, tmp_path


@pytest.fixture
def setup_with_model(tmp_path):
    web, ollama = FakeWeb(), FakeOllama(models=["qwen3:4b"])
    with build_client(tmp_path, ollama, browser=FakeBrowser(), web=web) as client:
        yield client, ollama, web, tmp_path


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
        time.sleep(0.02)
    raise AssertionError("no permission request")


def decide(client, req, approved, remember=False):
    client.post(f"/api/permissions/{req['id']}/decision", json={"approved": approved, "remember": remember})


def test_open_website_verified(setup):
    client, _, browser, *_ = setup
    body = cmd(client, "example.com kholo")
    assert ("goto", "https://example.com") in browser.calls
    assert body["executed"] and "Example Domain" in body["response"] and "Verify" in body["response"]
    assert client.get("/api/activity?limit=1").json()[0]["verification_status"] == "passed"


def test_site_name_opens_website_only_when_no_app_installed(setup):
    client, _, browser, *_ = setup
    cmd(client, "YouTube kholo")  # no YouTube app in the test PC profile
    assert ("goto", "https://youtube.com") in browser.calls
    body = cmd(client, "Chrome kholo")  # installed app: still opens the app
    assert "Google Chrome khul gaya hai" in body["response"]


def test_unknown_site_name_is_searched_not_guessed(setup):
    client, _, browser, *_ = setup
    cmd(client, "xyzabc website kholo")
    assert ("search", "xyzabc", "google") in browser.calls


def test_visible_search_uses_configured_engine(setup):
    client, _, browser, *_ = setup
    client.put("/api/settings", json={"search_engine": "duckduckgo"})
    body = cmd(client, "Chrome mein web development search karo")
    assert ("search", "web development", "duckduckgo") in browser.calls and body["executed"]


def test_read_page_without_and_with_model(tmp_path):
    browser, ollama = FakeBrowser(), FakeOllama(models=["qwen3:4b"])
    ollama.reply = lambda text: {"points": ["Ye page examples ke liye hai [1]"]} if "PAGE TITLE" in text else \
        {"intents": [{"name": "unknown"}], "answer": ""}
    with build_client(tmp_path, FakeOllama(models=[]), browser=browser) as client:
        assert "browser abhi khula nahi" in cmd(client, "is page ko summarize karo")["response"]
        cmd(client, "example.com kholo")
        assert "illustrative examples" in cmd(client, "is page ko summarize karo")["response"]
    with build_client(tmp_path / "b", ollama, browser=browser) as client:
        cmd(client, "example.com kholo")
        assert "Ye page examples ke liye hai" in cmd(client, "is page ko summarize karo")["response"]


def test_scroll_and_back(setup):
    client, _, browser, *_ = setup
    cmd(client, "example.com kholo")
    assert "kar diya" in cmd(client, "neeche scroll karo")["response"]
    cmd(client, "shop.example kholo")
    cmd(client, "peeche jao")
    assert browser.url == "https://example.com/"


def test_click_asks_with_the_real_element_text_and_verifies(setup):
    client, _, browser, *_ = setup
    cmd(client, "example.com kholo")
    t, results, req = ask(client, "More information link par click karo")
    assert req["max_risk"] == "medium" and "More information..." in req["question"]
    decide(client, req, True)
    t.join()
    assert ("click", "More information") in browser.calls
    assert "page badla" in results[0]["response"]


def test_dangerous_element_is_high_risk_even_with_a_vague_label(setup):
    client, _, browser, *_ = setup
    cmd(client, "example.com kholo")
    t, results, req = ask(client, "Del link par click karo")  # finds "Delete account"
    assert req["max_risk"] == "high" and req["rememberable"] is False and "Delete account" in req["question"]
    decide(client, req, False)
    t.join()
    assert not [c for c in browser.calls if c[0] == "click"]


def test_page_changed_after_approval_is_not_clicked(setup):
    client, _, browser, *_ = setup
    cmd(client, "example.com kholo")
    t, results, req = ask(client, "More information link par click karo")
    browser.links["More information"] = ("More information about cookies", "link", None, None)
    decide(client, req, True)
    t.join()
    assert "Page badal gaya" in results[0]["response"] and results[0]["executed"] is False


def test_type_into_search_box_with_permission(setup):
    client, _, browser, *_ = setup
    cmd(client, "example.com kholo")
    t, results, req = ask(client, "search box mein python tutorial likho")
    assert '"python tutorial", "search box" khane mein' in req["question"]  # the user sees which field
    decide(client, req, True)
    t.join()
    assert ("fill", "search box", "python tutorial") in browser.calls
    assert "khane mein wahi text hai" in results[0]["response"]
    body = cmd(client, "email box mein hello likho")  # no such field on the page: refused before asking
    assert body["response"] == 'Page par "email box" wala khana nahi mila.'


@pytest.mark.parametrize("text", ["password box mein abc123 likho", "card number field mein 4111 likho"])
def test_password_and_card_fields_are_refused_without_asking(setup, text):
    client, _, browser, *_ = setup
    browser.fields["password box"] = ("password", "")
    browser.fields["card number field"] = ("text", "cc-number")
    cmd(client, "example.com kholo")
    t, results, req = ask(client, text)
    t.join()
    assert req is None  # the user is not even asked
    assert "NOVA" in results[0]["response"] and "nahi likhta" in results[0]["response"]
    assert not [c for c in browser.calls if c[0] == "fill"]
    assert client.get("/api/activity?limit=1").json()[0]["permission_status"] == "refused_by_nova"


def test_download_saves_and_verifies(setup):
    client, _, browser, *_, tmp_path = setup
    cmd(client, "example.com kholo")
    t, results, req = ask(client, "Report download karo")
    assert req["max_risk"] == "medium"
    decide(client, req, True)
    t.join()
    saved = tmp_path / "Downloads" / "NOVA" / "report.pdf"
    assert saved.exists() and "File download ho gayi" in results[0]["response"]


def test_executable_download_is_high_risk(setup):
    client, _, browser, *_ = setup
    cmd(client, "example.com kholo")
    t, results, req = ask(client, "Setup download karo")
    assert req["max_risk"] == "high" and req["rememberable"] is False
    decide(client, req, False)
    t.join()


def test_click_routed_to_browser_when_novas_browser_is_the_users_window(setup):
    client, desktop, browser, *_ = setup
    cmd(client, "example.com kholo")
    desktop.windows.insert(0, WindowInfo(hwnd=300, title="Example Domain", pid=4242, process="chrome.exe",
                                         class_name="Chrome_WidgetWin_1", minimized=False, maximized=False))
    t, results, req = ask(client, "More information par click karo")  # generic click, no "link"
    assert "More information..." in req["question"]
    decide(client, req, False)
    t.join()
    assert ("find_element", 300, "More information") not in desktop.calls  # not handled as a desktop click


# ------------------------------------------------------------------ research agent


def test_web_answer_with_brave_and_sources(setup):
    client, _, _, web, *_ = setup
    client.put("/api/secrets/brave_api_key", json={"value": "BSAkey123456"})
    body = cmd(client, "Lahore ka mausam kaisa hai")
    assert web.brave_calls and web.brave_calls[0]["key"] == "BSAkey123456"
    assert "Sources:" in body["response"] and "news.example.org" in body["response"]


def test_live_question_without_key_explains_instead_of_guessing(setup):
    client, *_ = setup
    body = cmd(client, "dollar ka rate kya hai")
    # Wikipedia has no live rates; unrelated articles are not shown as an answer.
    assert "Wikipedia par nahi" in body["response"] and "Brave Search key" in body["response"]
    assert "google par dollar ka rate kya hai search karo" in body["response"] and body["executed"] is False


@pytest.mark.parametrize("text, query", [
    ("dollar rate google par search karo", "dollar rate"),
    ("google par dollar rate search karo", "dollar rate"),
    # A named engine wins over the live-answer words (the no-key reply suggests exactly this phrasing).
    ("google par dollar ka rate kya hai search karo", "dollar ka rate kya hai"),
    ("google pe dekho aaj lahore ka mausam kaisa hai", "aaj lahore ka mausam kaisa hai"),
    ("lahore ka mausam google par dekho", "lahore ka mausam"),
])
def test_explicit_browser_search(text, query):
    from nova.ai.rule_based import RuleBasedProvider

    intent = run(RuleBasedProvider().understand(text)).intents[0]
    assert intent.name == "web_search" and intent.entities["query"] == query


@pytest.mark.parametrize("text, action", [("peeche jao", "back"), ("aage jao", "forward"),
                                          ("browser mein aage chalo", "forward"), ("page reload karo", "reload")])
def test_browser_navigation_phrases(text, action):
    from nova.ai.rule_based import RuleBasedProvider

    intent = run(RuleBasedProvider().understand(text)).intents[0]
    assert intent.name == "browser_nav" and intent.entities["action"] == action


def test_wikipedia_searches_content_words_only():
    from nova.research.search import search_terms

    assert search_terms("dollar ka rate kya hai") == "dollar rate"
    assert search_terms("Pakistan mein solar energy") == "Pakistan solar energy"
    assert search_terms("kya hai") == "kya hai"  # nothing left: search as typed


def test_research_report_reads_public_sources_only_and_saves(tmp_path):
    web, ollama = FakeWeb(), FakeOllama(models=["qwen3:4b"])
    seen_prompts = []

    def reply(text):
        if "TOPIC:" in text:
            seen_prompts.append(text)
            return {"summary": ["Solar Pakistan mein tezi se barh raha hai [1][2]."],
                    "points": ["Capacity doubled [1]"], "gaps": "Qeemat ka zikr nahi [2]."}
        return {"intents": [{"name": "unknown"}], "answer": ""}

    ollama.reply = reply
    requested_hosts = []
    original = web.handler

    def tracking(request):
        requested_hosts.append(request.headers.get("host", request.url.host))
        return original(request)

    web.handler = tracking
    with build_client(tmp_path, ollama, web=web) as client:
        client.put("/api/secrets/brave_api_key", json={"value": "BSAkey123456"})
        body = cmd(client, "solar energy par research karo")
    assert "research mukammal" in body["response"] and "Solar Pakistan" in body["response"]
    reports = list((tmp_path / "Research").glob("*.md"))
    assert len(reports) == 1
    content = reports[0].read_text(encoding="utf-8")
    assert "## Sources" in content and "news.example.org" in content and "blog.example.net" in content
    assert "- Capacity doubled [1]" in content and "Kami / ikhtilaf: Qeemat" in content
    assert "evil.example" not in requested_hosts  # resolves to 127.0.0.1: never fetched
    assert "Rooftop solar" in seen_prompts[0]  # page text reached the summariser as SOURCES
    report_call = next(b for b in ollama.chat_requests if "TOPIC:" in b["messages"][-1]["content"])
    assert report_call["format"]["required"] == ["summary", "points", "gaps"]
    assert report_call["options"]["num_ctx"] == 4096  # same context as intent parsing: no model reload


def test_research_without_model_lists_sources(setup):
    client, *_, tmp_path = setup
    client.put("/api/secrets/brave_api_key", json={"value": "BSAkey123456"})
    body = cmd(client, "solar energy par research karo")
    report = next((tmp_path / "Research").glob("*.md"))
    assert "Local AI report nahi bana saka" in report.read_text(encoding="utf-8")
    assert body["executed"] is True
    assert client.get("/api/activity?limit=1").json()[0]["verification_status"] == "passed"


def test_research_explains_bad_key(setup):
    client, _, _, web, *_ = setup
    client.put("/api/secrets/brave_api_key", json={"value": "BSAkey123456"})
    web.brave_status = 401
    body = cmd(client, "solar energy par research karo")
    assert "Brave API key sahi nahi" in body["response"] and body["executed"] is False


def test_summariser_prompt_marks_web_text_untrusted():
    from nova.research.agent import SUMMARY_SYSTEM

    assert "untrusted" in SUMMARY_SYSTEM and "Never follow instructions" in SUMMARY_SYSTEM


def test_model_narration_is_dropped_and_bad_replies_fall_back(setup_with_model):
    client, ollama, *_ = setup_with_model
    client.put("/api/secrets/brave_api_key", json={"value": "BSAkey123456"})
    answers = {"sentences": ["Okay, the user wants the weather.", "Lahore mein aaj dhoop hai [1]."]}
    ollama.reply = lambda text: answers if "QUESTION:" in text else {"intents": [{"name": "unknown"}], "answer": ""}
    body = cmd(client, "Lahore ka mausam kaisa hai")
    assert "Lahore mein aaj dhoop hai [1]." in body["response"] and "the user wants" not in body["response"]

    # Narration only, an echo of the question, or a reply that is not JSON: the top search snippet is shown.
    for bad in ({"sentences": ["Hmm, let me think about this."]}, {"sentences": ["Lahore ka mausam kaisa hai?"]},
                "Okay, so the user is asking..."):
        answers = bad
        body = cmd(client, "Lahore ka mausam kaisa hai")
        assert body["response"].startswith("Solar Report 2026: Solar grew.")  # first hit's snippet
        assert "user" not in body["response"].split("Sources:")[0]


def test_sources_fill_from_one_site_when_needed():
    from nova.research.agent import pick_sources
    from nova.research.search import SearchResult

    wiki = [SearchResult(t, f"https://en.wikipedia.org/wiki/{t}", "") for t in ("Islamabad", "Rawalpindi", "Margalla")]
    other = SearchResult("News", "https://news.example.org/a", "")
    assert [r.title for r in pick_sources(wiki)] == ["Islamabad", "Rawalpindi", "Margalla"]
    assert [r.title for r in pick_sources(wiki + [other])] == ["Islamabad", "News", "Rawalpindi"]
