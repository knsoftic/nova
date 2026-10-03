"""Phase 12: installed NOVA - configuration, first-run setup (AI model download on request), runtime packaging."""

import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import FakeOllama, build_client
from nova import install
from nova.config import PROJECT_ROOT, load_settings

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND / "scripts"))
import build_runtime  # noqa: E402


def events(client, kind):
    return [e for e in client.app.state.bus.history() if e.type.value == kind]


# ------------------------------------------------------------------ configuration


def test_development_and_installed_configuration(monkeypatch, tmp_path):
    for name in ("NOVA_PACKAGED", "NOVA_LOGS_PATH", "NOVA_README_PATH", "NOVA_MODELS_DIR", "NOVA_DATA_DIR"):
        monkeypatch.delenv(name, raising=False)
    dev = load_settings()
    assert dev.packaged is False and dev.logs_path == PROJECT_ROOT / "LOGS.md"
    assert dev.models_dir == dev.data_dir / "models"
    monkeypatch.setenv("NOVA_PACKAGED", "1")
    monkeypatch.setenv("NOVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NOVA_MODELS_DIR", str(tmp_path / "models"))
    installed = load_settings()
    assert installed.packaged and installed.logs_path is None and installed.readme_path is None
    assert installed.data_dir == tmp_path / "data" and installed.models_dir == tmp_path / "models"
    monkeypatch.setenv("NOVA_LOGS_PATH", str(tmp_path / "LOGS.md"))
    assert load_settings().logs_path == tmp_path / "LOGS.md"
    monkeypatch.delenv("NOVA_PACKAGED")
    monkeypatch.setenv("NOVA_LOGS_PATH", "")  # empty switches it off in development too
    assert load_settings().logs_path is None


def test_install_info_finds_the_voice_models(tmp_path):
    settings = type("S", (), {})()
    settings.packaged, settings.data_dir, settings.logs_path = True, tmp_path / "data", None
    settings.models_dir = tmp_path / "models"
    info = install.install_info(settings)
    assert info["voice_models"] == {"whisper": False, "piper": False} and info["version"] == "0.12.0"
    (tmp_path / "models" / "whisper" / "models--x" / "snapshots" / "abc").mkdir(parents=True)
    (tmp_path / "models" / "whisper" / "models--x" / "snapshots" / "abc" / "model.bin").write_bytes(b"x")
    (tmp_path / "models" / "piper").mkdir(parents=True)
    (tmp_path / "models" / "piper" / "ur.onnx").write_bytes(b"x")
    assert install.install_info(settings)["voice_models"] == {"whisper": True, "piper": True}
    assert isinstance(install.install_info(settings)["startup_registered"], bool)


# ------------------------------------------------------------------ first-run setup


def test_setup_status_and_settings(tmp_path, monkeypatch):
    monkeypatch.setattr("nova.main.ollama_path", lambda: None)
    with build_client(tmp_path) as c:
        status = c.get("/api/setup/status").json()
        assert status["setup_done"] is False and status["start_with_windows"] is False
        assert status["ollama"] == {"installed": False, "reachable": True, "model": "qwen3:4b", "model_ready": False,
                                    "pulling": False}
        assert status["install"]["packaged"] is False
        s = c.put("/api/settings", json={"setup_done": True, "start_with_windows": True, "startup_mode": "silent"}).json()
        assert s["setup_done"] and s["start_with_windows"] and s["startup_mode"] == "silent"


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met")


def test_the_ai_model_is_downloaded_only_on_request_with_progress(tmp_path):
    ollama = FakeOllama(models=[])
    with build_client(tmp_path, ollama) as c:
        assert c.get("/api/setup/status").json()["ollama"]["model_ready"] is False
        assert c.post("/api/setup/pull-model").json() == {"started": True}
        wait_for(lambda: any(e.data.get("done") for e in events(c, "SETUP_PROGRESS")))
        progress = events(c, "SETUP_PROGRESS")
        assert [e.data["percent"] for e in progress if e.data.get("percent") is not None] == [10, 40, 70, 100]
        assert progress[-1].data == {"step": "model", "done": True, "ok": True}
        assert progress[-1].message == "AI model qwen3:4b tayyar"
        assert c.get("/api/setup/status").json()["ollama"]["model_ready"] is True
        row = c.get("/api/activity?q=ollama_pull").json()[0]
        assert row["execution_status"] == "success" and row["verification_status"] == "passed"


def test_a_failed_download_is_reported(tmp_path):
    ollama = FakeOllama(models=[])
    ollama.pull_ok = False
    with build_client(tmp_path, ollama) as c:
        c.post("/api/setup/pull-model")
        wait_for(lambda: any(e.data.get("done") for e in events(c, "SETUP_PROGRESS")))
        last = events(c, "SETUP_PROGRESS")[-1]
        assert last.data["ok"] is False and "disk full" in last.message
    with build_client(tmp_path / "b", FakeOllama(reachable=False)) as c:
        r = c.post("/api/setup/pull-model")
        assert r.status_code == 409 and "Ollama nahi chal raha" in r.json()["detail"]


# ------------------------------------------------------------------ self-test of the installation


def test_install_self_test(tmp_path, monkeypatch):
    with build_client(tmp_path) as c:
        run = c.post("/api/admin/selftest", json={"scope": "12"}).json()
        assert [(r["id"], r["status"]) for r in run["results"]] == [("install", "pass")]
        assert run["results"][0]["detail"].startswith("development")
        logs = {r["id"]: r for r in c.post("/api/admin/selftest", json={"scope": "11"}).json()["results"]}
        assert logs["logs_md"]["status"] == "info"  # no LOGS.md configured (like an installed NOVA)
        settings = c.app.state.settings
        object.__setattr__(settings, "packaged", True)
        object.__setattr__(settings, "models_dir_override", tmp_path / "no-models")
        assert c.post("/api/admin/selftest", json={"scope": "12"}).json()["results"][0]["status"] == "fail"
        (tmp_path / "no-models" / "whisper" / "m" / "snapshots" / "x").mkdir(parents=True)
        (tmp_path / "no-models" / "whisper" / "m" / "snapshots" / "x" / "model.bin").write_bytes(b"x")
        (tmp_path / "no-models" / "piper").mkdir()
        (tmp_path / "no-models" / "piper" / "v.onnx").write_bytes(b"x")
        c.put("/api/settings", json={"start_with_windows": True})
        monkeypatch.setattr(install, "startup_command", lambda: None)
        result = c.post("/api/admin/selftest", json={"scope": "12"}).json()["results"][0]
        assert result["status"] == "warn" and "registered nahi" in result["detail"]
        monkeypatch.setattr(install, "startup_command", lambda: '"C:\\NOVA\\NOVA.exe" --startup')
        assert c.post("/api/admin/selftest", json={"scope": "12"}).json()["results"][0]["status"] == "pass"


# ------------------------------------------------------------------ runtime packaging


def test_build_runtime_leaves_out_tests_and_dev_tools(tmp_path):
    assert build_runtime.is_dev_package("pytest") and build_runtime.is_dev_package("pytest-9.1.1.dist-info")
    assert build_runtime.is_dev_package("pip") and build_runtime.is_dev_package("py.py")
    assert not build_runtime.is_dev_package("pydantic") and not build_runtime.is_dev_package("piper")
    assert not build_runtime.is_dev_package("pipes") and not build_runtime.is_dev_package("pycaw")
    src = tmp_path / "src"
    (src / "keep" / "__pycache__").mkdir(parents=True)
    (src / "keep" / "a.py").write_text("x")
    (src / "keep" / "__pycache__" / "a.cpython-314.pyc").write_text("x")
    (src / "test").mkdir()
    (src / "test" / "t.py").write_text("x")
    size = build_runtime.copy_tree(src, tmp_path / "dst", lambda rel, name: rel == "." and name == "test")
    assert size == 1 and (tmp_path / "dst" / "keep" / "a.py").exists()
    assert not (tmp_path / "dst" / "test").exists() and not (tmp_path / "dst" / "keep" / "__pycache__").exists()


def test_runtime_check_command():
    result = subprocess.run([sys.executable, "-m", "nova", "--check"], cwd=BACKEND, capture_output=True, text=True,
                            timeout=300)
    assert result.returncode == 0 and "OK: 22 modules" in result.stdout


@pytest.mark.skipif(not (PROJECT_ROOT / "desktop" / "build" / "runtime" / "python" / "python.exe").exists(),
                    reason="the installer runtime has not been built (scripts/build_runtime.py)")
def test_the_built_runtime_runs_nova():
    runtime = PROJECT_ROOT / "desktop" / "build" / "runtime"
    env = {"SYSTEMROOT": r"C:\Windows", "PYTHONNOUSERSITE": "1", "PATH": r"C:\Windows\System32"}
    result = subprocess.run([str(runtime / "python" / "python.exe"), "-m", "nova", "--check"], cwd=runtime / "backend",
                            capture_output=True, text=True, timeout=300, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert str(runtime / "python") in result.stdout  # its own Python, not the developer's
