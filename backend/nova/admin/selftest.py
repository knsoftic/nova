"""Self-test: safe checks that NOVA's parts work on this PC - nothing is opened, sent, changed or deleted.

Quick checks run quietly at every start (only problems are reported); the full test (local AI answer, Urdu voice)
runs from the Admin panel. Each check belongs to a phase, so "Test Feature" runs exactly that phase's checks.
Statuses: pass, info (fine, but optional - e.g. no Outlook account), warn (works with a limitation), fail.
"""

from __future__ import annotations

import asyncio
import math
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

CheckFn = Callable[[], Any]  # returns (status, detail), or an awaitable of it
TIMEOUT_S = 90.0
LOCAL_AI_TIMEOUT_S = 120.0


@dataclass
class Check:
    id: str
    phase: str
    name: str  # Roman Urdu, shown in the Admin panel
    fn: CheckFn
    quick: bool = True
    timeout: float = TIMEOUT_S


class SelfTest:
    def __init__(self, checks: list[Check]) -> None:
        self.checks = checks

    def select(self, scope: str) -> list[Check]:
        if scope == "startup":
            return [c for c in self.checks if c.quick]
        if scope == "full":
            return list(self.checks)
        return [c for c in self.checks if c.phase.lower() == scope.lower()]

    async def run(self, scope: str) -> list[dict[str, Any]]:
        results = []
        for check in self.select(scope):
            started = time.perf_counter()
            try:
                out = check.fn()
                if asyncio.iscoroutine(out):
                    status, detail = await asyncio.wait_for(out, check.timeout)
                else:
                    status, detail = out  # type: ignore[misc]
            except asyncio.TimeoutError:
                status, detail = "fail", f"{int(check.timeout)}s mein jawab nahi aaya"
            except Exception as exc:  # a broken part must not stop the other checks
                status, detail = "fail", f"{type(exc).__name__}: {str(exc)[:160]}"
            results.append({"id": check.id, "phase": check.phase, "name": check.name, "status": status,
                            "detail": detail, "ms": int((time.perf_counter() - started) * 1000)})
        return results


def thread(fn: Callable[[], tuple[str, str]]) -> Callable[[], Awaitable[tuple[str, str]]]:
    """Run a blocking check off the event loop."""
    async def wrapper() -> tuple[str, str]:
        return await asyncio.to_thread(fn)
    return wrapper


# ------------------------------------------------------------------ the checks (built from the running app's parts)

def build_checks(app: Any) -> list[Check]:
    """`app` is the FastAPI app state (db, discovery, providers, voice, file_scope, ...)."""
    s = app

    def database() -> tuple[str, str]:
        con = sqlite3.connect(s.db_path)
        try:
            ok = con.execute("PRAGMA integrity_check").fetchone()[0]
            tables = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0]
        finally:
            con.close()
        return ("pass", f"integrity ok, {tables} tables") if ok == "ok" else ("fail", f"integrity: {ok}")

    def data_dir() -> tuple[str, str]:
        folder: Path = s.data_dir
        probe = folder / ".nova-selftest"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        free_gb = shutil.disk_usage(folder).free / 1024 ** 3
        if free_gb < 1:
            return "warn", f"drive par sirf {free_gb:.1f} GB khaali"
        return "pass", f"likh sakte hain, {free_gb:.0f} GB khaali"

    def profile() -> tuple[str, str]:
        p = s.discovery.profile
        if p is None:
            return "warn", "abhi scan nahi hua (start par background mein hota hai)"
        return "pass", f"{len(p.apps)} apps, scan {p.scanned_at[:16].replace('T', ' ')}"

    async def rules_brain() -> tuple[str, str]:
        samples = [("Chrome kholo", "open_app"), ("RAM batao", "system_info"),
                   ("Downloads mein pdf files dhoondo", "search_files"), ("volume 30 kar do", "change_setting"),
                   ("yaad rakho ke mujhe chai pasand hai", "remember_fact"), ("shukriya", "thanks")]
        wrong = []
        for text, want in samples:
            got = (await s.providers.rules.understand(text)).intents[0].name
            if got != want:
                wrong.append(f"\"{text}\" → {got}")
        return ("pass", f"{len(samples)}/{len(samples)} sahi") if not wrong else ("fail", "; ".join(wrong))

    async def local_ai_ready() -> tuple[str, str]:
        st = await s.providers.status(refresh=True)
        if st["mode"] == "rules":
            return "info", "Settings mein 'sirf rules' — local AI istemal nahi ho raha"
        if not st["ollama"]["reachable"]:
            return "warn", "Ollama nahi chal raha — NOVA rules se kaam karega"
        if not st["model_ready"]:
            return "warn", f"model {st['model']} install nahi (ollama pull {st['model']})"
        return "pass", f"{st['model']} tayyar (Ollama {st['ollama']['version']})"

    async def local_ai_answer() -> tuple[str, str]:
        if not await s.providers.ollama.is_available():
            return "warn", "model available nahi"
        started = time.perf_counter()
        try:  # the first answer also loads the model into memory - slow on a cold PC, but not broken
            u = await s.providers.ollama.understand("Chrome kholo", timeout=LOCAL_AI_TIMEOUT_S)
        except httpx.TimeoutException:
            return "warn", f"{int(LOCAL_AI_TIMEOUT_S)}s mein jawab nahi aaya (model load ho raha tha ya PC masroof hai)"
        took = time.perf_counter() - started
        if u.intents[0].name != "open_app":
            return "fail", f"\"Chrome kholo\" → {u.intents[0].name}"
        return ("pass" if took < 30 else "warn"), f"\"Chrome kholo\" sahi samjha ({took:.1f}s)"

    def voice_models() -> tuple[str, str]:
        stt, tts = s.voice.stt, s.voice.tts
        missing = [n for n, ok in (("Whisper", stt.model_downloaded()), ("Urdu voice", tts.is_available())) if not ok]
        if missing:
            return "warn", "download nahi: " + ", ".join(missing) + " (scripts/download_voice_models.py)"
        return "pass", f"whisper {stt.model_size}, {tts.voice}"

    def voice_speak() -> tuple[str, str]:
        if not s.voice.tts.is_available():
            return "warn", "Urdu voice download nahi"
        speech = s.voice.tts.synthesize("Self test.")
        return ("pass", f"{speech.duration_s:.1f}s awaaz bani") if speech.duration_s > 0 else ("fail", "khaali awaaz")

    def desktop() -> tuple[str, str]:
        windows = s.orchestrator.computer.desktop.list_windows()
        return "pass", f"{len(windows)} windows parhi"

    def permissions() -> tuple[str, str]:
        from ..permissions.engine import TargetContext, classify

        big = classify("delete_file", {}, "medium", TargetContext(count=500))[0]
        secret = classify("type_text", {"text": "mera password 1234"}, "medium", TargetContext())[0]
        terminal = classify("type_text", {"text": "dir"}, "medium", TargetContext(process="cmd.exe"))[0]
        if (big, secret, terminal) != ("high", "high", "high"):
            return "fail", f"risk ghalat: {big}, {secret}, {terminal}"
        return "pass", f"khatre ke qaide sahi; {len(s.db.list_permission_rules())} yaad rakhi ijazatein"

    def browser() -> tuple[str, str]:
        from ..design.agent import app_path

        channel = s.user_settings.browser_channel
        exe = {"chrome": "chrome.exe", "msedge": "msedge.exe"}[channel]
        return ("pass", f"{channel} mili") if app_path(exe) else ("warn", f"{channel} is PC par nahi mila")

    def web_search() -> tuple[str, str]:
        from ..secret_store import get_secret

        if get_secret(s.db, "brave_api_key"):
            return "pass", "Brave Search API key set hai"
        return "info", "Brave key nahi — research Wikipedia se (Settings → Web)"

    def folders() -> tuple[str, str]:
        roots = s.file_scope.roots()
        missing = [r.name for r in roots if not Path(r.path).is_dir()]
        if missing:
            return "warn", "nahi mile: " + ", ".join(missing)
        return "pass", f"{len(roots)} folders"

    def dev_tools() -> tuple[str, str]:
        tools = s.tools()
        found = [n for n, v in (("VS Code", tools.code), ("Python", tools.python), ("npm", tools.npm)) if v]
        missing = [n for n in ("VS Code", "Python", "npm") if n not in found]
        return ("pass", ", ".join(found) + " mile") if not missing else ("info", "nahi mile: " + ", ".join(missing))

    def windows_settings() -> tuple[str, str]:
        level = s.windows_settings.volume()
        return "pass", f"volume parha: {level}%"

    def messages() -> tuple[str, str]:
        wa = s.whatsapp.installed()
        outlook = s.mailer.outlook_ready()
        detail = f"WhatsApp {'mila' if wa else 'nahi mila'}, Outlook {'set hai' if outlook else 'set nahi (email draft)'}"
        return ("pass" if wa and outlook else "info"), detail

    def design() -> tuple[str, str]:
        from PIL import Image, ImageDraw

        from ..design import images

        img = Image.new("RGB", (200, 80), (20, 20, 20))
        ImageDraw.Draw(img).text((10, 20), "NOVA", fill=(255, 255, 255), font=images.font(32))
        return "pass", "Pillow aur font theek"

    def memory() -> tuple[str, str]:
        db = s.db
        return "pass", (f"{len(db.list_memories())} yaadein, {len(db.list_workflows())} workflows, history "
                        f"{s.user_settings.history_days or 'hamesha'} din")

    def behavior() -> tuple[str, str]:
        import numpy as np

        from ..behavior.estimator import BehaviorEstimator
        from ..behavior.signals import voice_features

        estimate = BehaviorEstimator().estimate("jaldi se Chrome kholo", [])
        tone = (8000 * np.sin(2 * math.pi * 200 * np.arange(32000) / 16000)).astype(np.int16).tobytes()
        v = voice_features(bytes(8000) + tone + bytes(8000), "mera system check karo")
        if estimate.state != "hurried" or v is None or not v.pitch_hz or abs(v.pitch_hz - 200) > 15:
            return "fail", f"andaza {estimate.state}, pitch {v.pitch_hz if v else None}"
        return "pass", "andaza aur awaaz ki pehchan theek"

    def logs_md() -> tuple[str, str]:
        from .docs import parse_tasks

        logs = s.admin.logs
        if logs.path is None:
            return "info", "installed NOVA — LOGS.md development ka hissa hai, yahan nahi"
        if not logs.available:
            return "warn", "LOGS.md nahi mili — approvals aur khulasa wahan nahi likhe jayenge"
        if not os.access(logs.path, os.W_OK):
            return "warn", "LOGS.md mein likh nahi sakte"
        return "pass", f"{len(parse_tasks(logs.read()))} tasks"

    def redaction() -> tuple[str, str]:
        from ..redaction import redact

        out = redact("password=hunter2 api_key=sk-ABCDEF1234567890 token: abcdef123456")
        leaked = [w for w in ("hunter2", "sk-ABCDEF1234567890", "abcdef123456") if w in (out or "")]
        return ("fail", "chhupaya nahi: " + ", ".join(leaked)) if leaked else ("pass", "passwords/keys chhup gaye")

    def install() -> tuple[str, str]:
        from ..install import install_info

        info = install_info(s.settings)
        kind = "installed" if info["packaged"] else "development"
        missing = [n for n, ok in info["voice_models"].items() if not ok]
        if s.user_settings.start_with_windows and info["packaged"] and not info["startup_registered"]:
            return "warn", "Settings mein 'Windows ke sath start' on hai lekin Windows mein NOVA registered nahi"
        if missing and info["packaged"]:
            return "fail", "program ke sath voice models nahi: " + ", ".join(missing)
        start = "Windows ke sath start" if info["startup_registered"] else "khud start nahi"
        return "pass", f"{kind} · Python {info['python'].split()[0]} · {start}"

    async def multi_pc() -> tuple[str, str]:
        from ..multipc.link import loopback_selftest

        if not await loopback_selftest():  # the encrypted link itself (TLS 1.3 + pre-shared key) on 127.0.0.1
            return "fail", "Encrypted link (TLS-PSK) is Python mein nahi chal raha"
        st = s.multipc.status()
        if not st["enabled"]:
            return "info", "band hai (PCs tab se on karein) · encrypted link theek"
        if not st["running"]:
            return "warn", st["reason"] or "chal nahi raha"
        online = sum(p["online"] for p in st["peers"])
        return "pass", f"{len(st['peers'])} PC jure, {online} online · port {st['this']['port']}"

    return [
        Check("install", "12", "Installation aur Windows startup", thread(install)),
        Check("database", "1", "Database (SQLite) theek hai", thread(database)),
        Check("data_dir", "1", "Data folder mein likh sakte hain", thread(data_dir)),
        Check("profile", "2", "System profile maujood hai", profile),
        Check("rules_brain", "4", "AI brain (rules) sahi samajhta hai", rules_brain),
        Check("local_ai_ready", "4", "Local AI (Ollama) tayyar hai", local_ai_ready),
        Check("local_ai_answer", "4", "Local AI command samajhta hai", local_ai_answer, quick=False,
              timeout=LOCAL_AI_TIMEOUT_S + 30),
        Check("voice_models", "5", "Awaaz ke models maujood", thread(voice_models)),
        Check("voice_speak", "5", "Urdu awaaz ban sakti hai", thread(voice_speak), quick=False),
        Check("desktop", "6", "Windows ki list parh sakte hain", thread(desktop)),
        Check("permissions", "7", "Permission Engine ke qaide sahi", thread(permissions)),
        Check("browser", "8A", "Browser (Chrome/Edge) maujood", thread(browser)),
        Check("web_search", "8A", "Web search", thread(web_search)),
        Check("folders", "8B", "Allowed folders maujood", thread(folders)),
        Check("dev_tools", "8B", "Coding tools (VS Code, Python, npm)", thread(dev_tools)),
        Check("windows_settings", "8C", "Windows settings parh sakte hain", thread(windows_settings)),
        Check("messages", "8C", "WhatsApp / Outlook", thread(messages)),
        Check("design", "8C", "Tasveer tools (Pillow + font)", thread(design)),
        Check("memory", "9", "Memory (yaadein, workflows, history)", thread(memory)),
        Check("behavior", "10", "Behavior layer (andaza, awaaz)", thread(behavior)),
        Check("logs_md", "11", "LOGS.md parh/likh sakte hain", thread(logs_md)),
        Check("redaction", "11", "Logs mein secrets chhupaye jate hain", thread(redaction)),
        Check("multi_pc", "13", "Multi-PC (doosre PCs se encrypted jor)", multi_pc),
    ]
