import asyncio
import sys

import pytest

from conftest import GB, make_profile
from nova.ai.rule_based import RuleBasedProvider
from nova.discovery.apps import find_app, merge_apps
from nova.discovery.models import AppEntry, GpuInfo
from nova.discovery.recommend import recommend
from nova.discovery.windows import as_list


def detect(text):
    return asyncio.run(RuleBasedProvider().detect_intent(text))


# ------------------------------------------------------------------ app matching


@pytest.mark.parametrize(
    "query,expected",
    [
        ("chrome", "Google Chrome"),
        ("Chrome", "Google Chrome"),
        ("کروم", "Google Chrome"),
        ("क्रोम", "Google Chrome"),
        ("vs code", "Visual Studio Code"),
        ("whatsapp", "WhatsApp"),  # not "WhatsApp Beta"
        ("واٹس ایپ", "WhatsApp"),
        ("photoshop", "Adobe Photoshop CC 2019"),
        ("file explorer", "File Explorer"),
        ("whatsap", "WhatsApp"),  # fuzzy
    ],
)
def test_find_app(query, expected):
    match = find_app(make_profile().apps, query)
    assert match is not None
    assert match.app.name == expected


def test_find_app_missing():
    assert find_app(make_profile().apps, "telegram") is None
    assert find_app(make_profile().apps, "") is None


def test_merge_apps_combines_sources_and_drops_junk():
    start = [
        {"Name": "Google Chrome", "AppID": "Chrome"},
        {"Name": "Uninstall Foo", "AppID": "x"},
        {"Name": "Foo Readme", "AppID": "y"},
    ]
    registry = [
        AppEntry(name="Google Chrome", version="140.0", publisher="Google LLC", sources=["registry"]),
        AppEntry(name="Some Tool (x64)", version="1.0", sources=["registry"]),
    ]
    apps = merge_apps(start, registry, {"chrome.exe": r"C:\Chrome\chrome.exe"})
    names = [a.name for a in apps]
    assert names == ["Google Chrome", "Some Tool (x64)"]
    chrome = apps[0]
    assert chrome.version == "140.0"
    assert chrome.app_id == "Chrome"
    assert set(chrome.sources) == {"start_menu", "registry", "app_paths"}
    assert chrome.executable == r"C:\Chrome\chrome.exe"


def test_as_list_handles_powershell_single_objects():
    assert as_list(None) == []
    assert as_list({"a": 1}) == [{"a": 1}]
    assert as_list([1, 2]) == [1, 2]


# ------------------------------------------------------------------ self-configuration


def recs(profile):
    return {r.key: r for r in recommend(profile)}


def test_recommend_nvidia_workstation():
    r = recs(make_profile(ram_total_bytes=32 * GB,
                          gpus=[GpuInfo(name="RTX 4090", memory_bytes=24 * GB, vendor="nvidia", dedicated=True)]))
    assert r["compute_device"].value == "cuda"
    assert r["ai_model_tier"].value == "large"
    assert "cuda" in r["stt_model"].value
    assert not r["ai_model_tier"].auto_applied  # models are suggested, never auto-installed


def test_recommend_cpu_only_laptop():
    r = recs(make_profile(ram_total_bytes=32 * GB,
                          gpus=[GpuInfo(name="AMD Radeon(TM) Graphics", memory_bytes=GB // 2, vendor="amd", dedicated=False)]))
    assert r["compute_device"].value == "cpu"
    assert r["ai_model_tier"].value == "small"
    assert "cpu" in r["stt_model"].value


def test_recommend_low_ram_and_no_devices():
    r = recs(make_profile(ram_total_bytes=4 * GB, gpus=[], microphones=[], speakers=[], displays=[]))
    assert r["ai_model_tier"].value == "rule_based_only"
    assert r["voice_input"].value == "unavailable"
    assert r["voice_output"].value == "unavailable"
    assert r["multi_monitor_awareness"].value == "disabled"


# ------------------------------------------------------------------ intents


@pytest.mark.parametrize(
    "text,intent,entities",
    [
        ("Hey NOVA, mera system check karo.", "system_info", {"topic": "summary"}),
        ("Hey NOVA, mera system profile batao.", "system_info", {"topic": "summary"}),
        ("System ki RAM check karo.", "system_info", {"topic": "ram"}),
        ("Windows ka version batao.", "system_info", {"topic": "windows"}),
        ("Available storage check karo.", "system_info", {"topic": "storage"}),
        ("CPU kitna use ho raha hai", "system_info", {"topic": "cpu"}),
        ("graphics card kaun sa hai", "system_info", {"topic": "gpu"}),
        ("kaun se browsers hain", "system_info", {"topic": "browsers"}),
        ("kaun si apps chal rahi hain", "system_info", {"topic": "running"}),
        ("kaun se apps installed hain", "system_info", {"topic": "apps"}),
        ("mic aur camera check karo", "system_info", {"topic": "devices"}),
        ("internet connected hai?", "system_info", {"topic": "network"}),
        ("kya photoshop installed hai", "app_check", {"app": "photoshop"}),
        ("is Telegram installed", "app_check", {"app": "Telegram"}),
        ("Chrome ko default browser bana do", "change_setting", {"request": "Chrome ko default browser bana do"}),
        ("system dobara scan karo", "rescan_system", {}),
    ],
)
def test_system_intents(text, intent, entities):
    result = detect(text)
    assert result.name == intent
    assert result.entities == entities


# ------------------------------------------------------------------ API + System Agent


def test_profile_endpoint_before_and_after_scan(client):
    assert client.get("/api/system/profile").json()["profile"] is None
    r = client.post("/api/system/scan").json()
    assert r["apps"] == 6
    profile = client.get("/api/system/profile").json()["profile"]
    assert profile["cpu"]["name"] == "Test CPU 9000"
    assert client.get("/api/system/apps/find", params={"q": "vs code"}).json()["match"]["app"]["name"] == "Visual Studio Code"


def test_scan_applies_only_runtime_settings_and_is_verified(client):
    client.post("/api/system/scan")
    activity = client.get("/api/activity").json()[0]
    assert activity["agent"] == "System Agent"
    assert activity["verification_status"] == "passed"
    # compute_device is a runtime setting (auto-applied); the AI model tier is only suggested
    db = client.app.state.db
    assert db.get_setting("compute_device") == "cuda"
    assert db.get_setting("ai_model_tier") is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("System ki RAM check karo", "RAM: total 16 GB, is waqt 9.0 GB free hai"),
        ("processor batao", "Test CPU 9000 (8 cores / 16 threads)"),
        ("Windows ka version batao", "Microsoft Windows 11 Pro 25H2 (build 26200)"),
        ("storage check karo", "C: 120 GB free / 500 GB"),
        ("kya photoshop installed hai", "Haan, Adobe Photoshop CC 2019 is PC par installed hai"),
        ("kya telegram installed hai", "nahi mili"),
        ("kaun se browsers hain", "Default browser: Google Chrome"),
        ("admin access hai?", "administrator hai, lekin NOVA normal"),
    ],
)
def test_system_agent_answers(client, text, expected):
    body = client.post("/api/command", json={"text": text}).json()
    assert expected in body["response"]
    assert body["executed"] is True


def test_open_app_reports_missing_app(client):
    body = client.post("/api/command", json={"text": "Telegram open karo"}).json()
    assert "nahi mila" in body["response"]
    assert body["executed"] is False


def test_change_setting_is_not_executed(client):
    body = client.post("/api/command", json={"text": "Chrome ko default browser bana do"}).json()
    assert body["executed"] is False
    assert "Permission Engine" in body["response"]


def test_system_summary_mentions_key_hardware(client):
    body = client.post("/api/command", json={"text": "mera system profile batao"}).json()
    for part in ("Test CPU 9000", "RAM", "RTX 4060", "Windows 11", "Microphone", "6 applications"):
        assert part in body["response"]


# ------------------------------------------------------------------ real Windows scan


@pytest.mark.skipif(sys.platform != "win32", reason="Windows discovery")
def test_real_windows_scan():
    from nova.discovery.scanner import live_stats, scan

    profile = scan()
    assert profile.cpu.name
    assert profile.cpu.threads and profile.cpu.threads >= 1
    assert profile.ram_total_bytes and profile.ram_total_bytes > GB
    assert profile.windows.build
    assert profile.drives
    assert len(profile.apps) > 0
    assert find_app(profile.apps, "file explorer") is not None  # built into every Windows install
    assert profile.recommendations
    stats = live_stats()
    assert 0 <= stats.cpu_percent <= 100
