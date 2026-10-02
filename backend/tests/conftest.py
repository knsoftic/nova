import json

import httpx
import pytest
from fastapi.testclient import TestClient

from nova.config import Settings
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


def build_client(tmp_path, ollama: FakeOllama | None = None):
    ollama = ollama or FakeOllama(models=[])  # reachable but no model: rules only, deterministic
    app = create_app(Settings(data_dir=tmp_path, discovery_on_startup=False), scanner=make_profile,
                     stats=fake_stats, ollama_transport=ollama.transport)
    return TestClient(app)


@pytest.fixture
def client(tmp_path):
    with build_client(tmp_path) as c:
        yield c


@pytest.fixture
def fake_ollama():
    return FakeOllama(models=["qwen3:4b"])


@pytest.fixture
def ai_client(tmp_path, fake_ollama):
    with build_client(tmp_path, fake_ollama) as c:
        yield c
