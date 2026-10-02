import json

import httpx
import pytest
from fastapi.testclient import TestClient

from nova.config import Settings
from nova.control.windows import WindowInfo
from nova.discovery.models import (
    AppEntry,
    AudioDevice,
    BrowserInfo,
    CpuInfo,
    DisplayInfo,
    DriveInfo,
    GpuInfo,
    LiveStats,
    PermissionsInfo,
    SystemProfile,
    WindowsInfo,
)
from nova.discovery.recommend import recommend
from nova.main import create_app

GB = 1024**3


def make_profile(**overrides) -> SystemProfile:
    profile = SystemProfile(
        scanned_at="2026-10-02T00:00:00+00:00",
        scan_duration_ms=10,
        platform="win32",
        cpu=CpuInfo(name="Test CPU 9000", cores=8, threads=16),
        ram_total_bytes=16 * GB,
        gpus=[GpuInfo(name="NVIDIA GeForce RTX 4060", memory_bytes=8 * GB, vendor="nvidia", dedicated=True)],
        drives=[DriveInfo(mountpoint="C:\\", filesystem="NTFS", total_bytes=500 * GB, free_bytes=120 * GB)],
        windows=WindowsInfo(caption="Microsoft Windows 11 Pro", build="26200", display_version="25H2",
                            architecture="64-bit", manufacturer="HP", model="TestBook"),
        microphones=[AudioDevice(name="Microphone (Test Audio)", kind="input")],
        speakers=[AudioDevice(name="Speakers (Test Audio)", kind="output")],
        cameras=["Test HD Camera"],
        displays=[DisplayInfo(name="DISPLAY1", primary=True, width=1920, height=1080)],
        network_connected=True,
        apps=[
            AppEntry(name="Google Chrome", app_id="Chrome", sources=["start_menu", "registry"], version="140.0"),
            AppEntry(name="Visual Studio Code", app_id="Microsoft.VisualStudioCode", sources=["start_menu"]),
            AppEntry(name="WhatsApp Beta", app_id="wa.beta!App", sources=["start_menu"]),
            AppEntry(name="WhatsApp", app_id="wa!App", sources=["start_menu"]),
            AppEntry(name="Adobe Photoshop CC 2019", app_id="ps", sources=["start_menu"]),
            AppEntry(name="File Explorer", app_id="Microsoft.Windows.Explorer", sources=["start_menu"]),
        ],
        browsers=[BrowserInfo(name="Google Chrome", is_default=True), BrowserInfo(name="Microsoft Edge")],
        permissions=PermissionsInfo(is_elevated=False, user_is_admin=True),
    )
    profile = profile.model_copy(update=overrides)
    profile.recommendations = recommend(profile)
    return profile


def fake_stats() -> LiveStats:
    return LiveStats(cpu_percent=12.0, ram_total_bytes=16 * GB, ram_available_bytes=9 * GB, ram_percent=44.0,
                     drives=[DriveInfo(mountpoint="C:\\", filesystem="NTFS", total_bytes=500 * GB, free_bytes=120 * GB)],
                     uptime_seconds=3600)


class FakeOllama:
    """In-process stand-in for the Ollama HTTP API. Tests never talk to a real model."""

    def __init__(self, models=(), reachable=True):
        self.models = list(models)
        self.reachable = reachable
        self.reply = None  # callable(user_text) -> dict | str (raw content) ; raise to simulate errors
        self.chat_requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if not self.reachable:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        if path == "/api/version":
            return httpx.Response(200, json={"version": "0.35.0"})
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m} for m in self.models]})
        if path == "/api/generate":
            return httpx.Response(200, json={"done": True})
        if path == "/api/chat":
            body = json.loads(request.content)
            self.chat_requests.append(body)
            user_text = body["messages"][-1]["content"]
            out = self.reply(user_text) if self.reply else {"intents": [{"name": "unknown"}], "answer": ""}
            content = out if isinstance(out, str) else json.dumps(out)
            return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})
        return httpx.Response(404)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


class FakeDesktop:
    """Stand-in for the Windows desktop: tests never open, focus or type into real windows."""

    def __init__(self):
        self.windows: list[WindowInfo] = [
            WindowInfo(hwnd=101, title="Inbox - Google Chrome", pid=11, process="chrome.exe",
                       class_name="Chrome_WidgetWin_1", minimized=False, maximized=False),
            WindowInfo(hwnd=102, title="notes.txt - Notepad", pid=12, process="Notepad.exe",
                       class_name="Notepad", minimized=False, maximized=False),
        ]
        self.calls: list[tuple] = []
        self.launch_outcome = "opened"
        self.focus_ok = True
        self.clipboard = 1
        self.copy_changes_clipboard = True

    foreground = None  # hwnd in front when a command is typed (None = not known)

    def list_windows(self):
        return list(self.windows)

    def foreground_hwnd(self):
        return self.foreground

    def last_user_window(self, exclude=None):
        exclude = exclude or set()
        return next((w for w in self.windows if w.hwnd not in exclude), None)

    def find_windows(self, name, executable=None):
        from nova.control.windows import window_matches

        return [w for w in self.windows if window_matches(w, name, executable)]

    def focus(self, hwnd, timeout=2.0):
        self.calls.append(("focus", hwnd))
        return self.focus_ok

    def set_state(self, hwnd, action):
        self.calls.append(("set_state", hwnd, action))
        return True

    def request_close(self, hwnd):
        self.calls.append(("close", hwnd))

    def window_exists(self, hwnd):
        return any(w.hwnd == hwnd for w in self.windows)

    def launch(self, app, **_):
        from nova.control.launcher import LaunchResult

        self.calls.append(("launch", app.name))
        if self.launch_outcome == "opened":
            self.windows.insert(0, WindowInfo(hwnd=200 + len(self.calls), title=app.name, pid=99,
                                              process="app.exe", class_name="X", minimized=False, maximized=False))
            return LaunchResult("opened", app.name, 0.8)
        return LaunchResult(self.launch_outcome, seconds=15.0)

    def read_window(self, hwnd, title, process):
        from nova.control.screen import ScreenReading, UiElement

        self.calls.append(("read", hwnd))
        return ScreenReading(window_title=title, process=process,
                             text_lines=["Inbox", "Meeting at 5 pm", "ok"],
                             elements=[UiElement("button", "Compose", 10, 10), UiElement("edit", "Search mail", 50, 10)])

    def save_screenshot(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "NOVA_test.png"
        path.write_bytes(b"\x89PNG fake")
        self.calls.append(("screenshot", str(path)))
        return path

    def hotkey(self, name):
        self.calls.append(("hotkey", name))
        if name in ("copy", "cut") and self.copy_changes_clipboard:
            self.clipboard += 1
        return True

    def clipboard_sequence(self):
        return self.clipboard

    # actions that need permission
    typed_field_value: str | None = None  # what the focused field reports after typing (None = not readable)
    close_works = True
    element_status = "invoked"

    def type_text(self, text):
        self.calls.append(("type", text))
        if self.typed_field_value == "":
            self.typed_field_value = text
        return True

    def focused_value(self):
        return self.typed_field_value

    def find_element(self, hwnd, label):
        from nova.control.screen import UiElement

        self.calls.append(("find_element", hwnd, label))
        if self.element_status == "not_found":
            return "not_found", None
        return self.element_status, UiElement("button", label, 300, 400)

    def click(self, x, y):
        self.calls.append(("click", x, y))
        return True

    def wait_closed(self, hwnd, timeout=5.0):
        if self.close_works:
            self.windows = [w for w in self.windows if w.hwnd != hwnd]
        return self.close_works


class FakeBrowser:
    """Stand-in for NOVA's Playwright browser: an in-memory set of pages."""

    PAGES = {
        "https://example.com/": ("Example Domain", "<html><body><main><h1>Example Domain</h1><p>This domain is for "
                                 "use in illustrative examples in documents. You may use this domain freely.</p>"
                                 "</main></body></html>"),
        "https://shop.example/": ("Shop", "<html><body><p>Buy things here.</p></body></html>"),
    }

    def __init__(self):
        self.open = False
        self.url = ""
        self.title = ""
        self.scroll = 0
        self.history: list[str] = []
        self.calls: list[tuple] = []
        # clickable elements on the current page: label -> (text, kind, href or None, "download:<name>")
        self.links = {"More information": ("More information...", "link", "https://www.iana.org/domains/example", None),
                      "Delete": ("Delete account", "button", None, None),
                      "Report": ("Annual report (PDF)", "link", "https://example.com/report.pdf", "download:report.pdf"),
                      "Setup": ("Download setup.exe", "link", "https://example.com/setup.exe", "download:setup.exe")}
        self.fields = {"search box": ("search", ""), "password": ("password", ""), "card number": ("text", "cc-number")}
        self.downloads_dir = None

    def is_open(self):
        return self.open

    def pid(self):
        return 4242 if self.open else None

    def state(self):
        from nova.browser.controller import PageState

        return PageState(self.title, self.url) if self.open else None

    def goto(self, url):
        from nova.browser.controller import PageState

        self.calls.append(("goto", url))
        self.open = True
        key = url if url.endswith("/") else url + "/"
        self.url = key if key in self.PAGES else url
        self.title = self.PAGES.get(key, (url.split("//")[-1].split("/")[0], ""))[0]
        self.history.append(self.url)
        return PageState(self.title, self.url)

    def search(self, query, engine):
        from urllib.parse import quote_plus

        self.calls.append(("search", query, engine))
        return self.goto(f"https://www.{engine}.com/search?q={quote_plus(query)}")

    def read(self):
        from nova.browser.controller import PageState

        if not self.open:
            return None
        html = self.PAGES.get(self.url, ("", "<html><body><p>Search results page.</p></body></html>"))[1]
        return PageState(self.title, self.url), html

    def navigate(self, action):
        from nova.browser.controller import PageState

        self.calls.append(("nav", action))
        before = (self.url, self.scroll)
        if action == "scroll_down":
            self.scroll += 700
        elif action == "scroll_up":
            self.scroll = max(0, self.scroll - 700)
        elif action == "back" and len(self.history) > 1:
            self.history.pop()
            self.url = self.history[-1]
        return PageState(self.title, self.url), (self.url, self.scroll) != before or action == "reload"

    def _find(self, label):
        for key, value in self.links.items():
            if label.lower() in (key.lower(), value[0].lower()) or label.lower() in value[0].lower():
                return value
        return None

    def inspect_click(self, label):
        from nova.browser.controller import ElementInfo

        found = self._find(label) if self.open else None
        return ElementInfo(True, found[0], found[1], found[2]) if found else ElementInfo(False)

    def inspect_field(self, label):
        from nova.browser.controller import ElementInfo

        if not self.open:
            return ElementInfo(False)
        key = (label or "search box").lower()
        if key not in self.fields:
            return ElementInfo(False)
        input_type, autocomplete = self.fields[key]
        return ElementInfo(True, key, "field", input_type=input_type, autocomplete=autocomplete, name=key)

    def click(self, label, expected_text):
        from nova.browser.controller import PageState

        self.calls.append(("click", label))
        found = self._find(label)
        if not found:
            return "not_found", None
        if found[0] != expected_text:
            return "changed_target", None
        if found[2]:
            return "clicked_changed", self.goto(found[2])
        return "clicked_same", PageState(self.title, self.url)

    def fill(self, label, text):
        self.calls.append(("fill", label, text))
        key = (label or "search box").lower()
        if key not in self.fields:
            return "not_found", None
        if self.fields[key][0] == "password":
            return "refused_password", None
        return "filled", text

    def download(self, label):
        self.calls.append(("download", label))
        found = self._find(label)
        if not found:
            return "not_found", None
        if not found[3]:
            return "not_a_download", None
        folder = self.downloads_dir
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / found[3].split(":", 1)[1]
        path.write_bytes(b"x" * 2048)
        return "saved", path

    def shutdown(self):
        pass


PUBLIC_TEST_IPS = {"en.wikipedia.org": "198.35.26.96", "example.com": "93.184.216.34",
                   "news.example.org": "93.184.216.35", "blog.example.net": "93.184.216.36",
                   "evil.example": "127.0.0.1"}


async def fake_resolver(host, port):
    if host not in PUBLIC_TEST_IPS:
        raise OSError("unknown host")
    return [PUBLIC_TEST_IPS[host]]


class FakeWeb:
    """Brave API, Wikipedia API and a few web pages, served from memory."""

    def __init__(self):
        self.brave_calls: list[dict] = []
        self.brave_status = 200
        self.pages = {
            "news.example.org": "<html><head><title>Solar Report</title></head><body><article><p>"
                                + "Solar power capacity grew strongly in 2026 across Pakistan. " * 30
                                + "</p></article></body></html>",
            "blog.example.net": "<html><head><title>Solar Blog</title></head><body><article><p>"
                                + "Rooftop solar is cheaper than grid power for many homes. " * 30
                                + "</p></article></body></html>",
            "example.com": "<html><head><title>Example</title></head><body><p>Example page.</p></body></html>",
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.headers.get("host", request.url.host)
        if request.url.host == "api.search.brave.com":
            self.brave_calls.append({"q": request.url.params.get("q"), "key": request.headers.get("x-subscription-token")})
            if self.brave_status != 200:
                return httpx.Response(self.brave_status, json={})
            return httpx.Response(200, json={"web": {"results": [
                {"title": "Solar Report 2026", "url": "https://news.example.org/solar", "description": "Solar grew.",
                 "extra_snippets": ["Capacity doubled."], "age": "2 days ago"},
                {"title": "Solar Blog", "url": "https://blog.example.net/solar", "description": "Rooftop solar."},
                {"title": "Local trick", "url": "http://evil.example/admin", "description": "should be skipped"},
                {"title": "Not web", "url": "file:///C:/secret.txt", "description": "never fetched"},
            ]}})
        if request.url.host == "en.wikipedia.org":
            params = request.url.params
            if params.get("list") == "search":
                return httpx.Response(200, json={"query": {"search": [
                    {"title": "Islamabad", "snippet": "capital of <b>Pakistan</b>"},
                    {"title": "Islamabad (disambiguation)", "snippet": "may refer to"},
                    {"title": "Capital", "snippet": "a capital"}]}})
            return httpx.Response(200, json={"query": {"pages": {
                "1": {"title": "Islamabad", "extract": "Islamabad is the capital city of Pakistan."},
                "2": {"title": "Islamabad (disambiguation)", "extract": "Islamabad may refer to:"},
                "3": {"title": "Capital", "extract": "Capital may refer to:"}}}})
        if host in self.pages:
            return httpx.Response(200, html=self.pages[host])
        return httpx.Response(404)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def build_client(tmp_path, ollama: FakeOllama | None = None, desktop: FakeDesktop | None = None,
                 permission_timeout_s: float = 0.5, browser: FakeBrowser | None = None, web: FakeWeb | None = None):
    ollama = ollama or FakeOllama(models=[])  # reachable but no model: rules only, deterministic
    browser = browser or FakeBrowser()
    browser.downloads_dir = tmp_path / "Downloads" / "NOVA"
    # Short permission timeout: an unanswered question resolves to "no" quickly in tests.
    app = create_app(Settings(data_dir=tmp_path, discovery_on_startup=False, permission_timeout_s=permission_timeout_s,
                              reports_dir=tmp_path / "Research"),
                     scanner=make_profile, stats=fake_stats, ollama_transport=ollama.transport,
                     desktop=desktop or FakeDesktop(), browser_controller=browser,
                     web_transport=(web or FakeWeb()).transport, web_resolver=fake_resolver)
    return TestClient(app)


@pytest.fixture
def client(tmp_path):
    with build_client(tmp_path) as c:
        yield c


@pytest.fixture
def desktop():
    return FakeDesktop()


@pytest.fixture
def control_client(tmp_path, desktop):
    with build_client(tmp_path, desktop=desktop) as c:
        yield c


@pytest.fixture
def fake_ollama():
    return FakeOllama(models=["qwen3:4b"])


@pytest.fixture
def ai_client(tmp_path, fake_ollama):
    with build_client(tmp_path, fake_ollama) as c:
        yield c
