"""FastAPI app: local REST API + WebSocket event stream for the NOVA desktop UI."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError

from . import __version__
from .ai.manager import ProviderManager
from .ai.ollama import OllamaProvider
from .agents.file_agent import FileAgent
from .agents.settings_agent import SettingsAgent
from .coding import CodingAgent, Tools, find_tools
from .communication import CommunicationAgent, Mailer, WhatsAppDesktop
from .communication.contacts import normalize_phone, valid_email
from .control.settings import WindowsSettings
from .design import DesignAgent
from .config import PROJECT_ROOT, Settings, load_settings
from .files import FileOps, FileScope
from .db import Database
from .discovery import DiscoveryService, LiveStats, SystemProfile, find_app
from .events import EventBus, EventType, NovaEvent
from .orchestrator import CommandResult, Orchestrator
from .agents.computer import ComputerAgent, Desktop
from .browser import BrowserController
from .browser.agent import BrowserAgent, site_for
from .behavior.layer import BehaviorLayer
from .known_folders import known_folder
from .memory import facts as memory_facts
from .memory.agent import NAME as MEMORY_AGENT
from .memory.agent import MemoryAgent
from .memory.history import PERIODS
from .memory.short_term import ShortTermMemory
from .memory.workflows import MAX_STEPS, StepResolver, numbered, workflow_key
from .research import ResearchAgent
from .secret_store import KNOWN_SECRETS, delete_secret, get_secret, masked, set_secret
from .permissions import PermissionEngine
from .voice import SpeechToText, TextToSpeech, VoiceService, VoiceSession
from .user_settings import (
    UserSettings,
    UserSettingsUpdate,
    apply_update,
    load_user_settings,
    save_user_settings,
)

log = logging.getLogger("nova")

MAX_COMMAND_LENGTH = 2000
MAX_AUDIO_FRAME_BYTES = 64_000  # 2 s of 16 kHz int16 per frame is far more than the UI sends


async def _background_scan(discovery: DiscoveryService) -> None:
    try:
        await discovery.run_scan(reason="startup")
    except Exception:  # already logged and published as DISCOVERY_FAILED
        pass


async def _prepare_ai(providers: ProviderManager, bus: EventBus) -> None:
    """Report whether the local model is usable and load it into memory so the first command is fast."""
    if providers.mode == "rules":
        await bus.publish(NovaEvent(type=EventType.AI_STATUS, agent="Orchestrator",
                                    message="AI mode: sirf rules (local model istemal nahi ho raha)",
                                    data=await providers.status(refresh=True)))
        return
    status = await providers.status(refresh=True)
    if not status["model_ready"]:
        reason = "Ollama nahi chal raha" if not status["ollama"]["reachable"] else f"model {status['model']} install nahi"
        await bus.publish(NovaEvent(type=EventType.AI_STATUS, agent="Orchestrator",
                                    message=f"AI model available nahi ({reason}) — rules se kaam ho raha hai",
                                    data=status))
        return
    await bus.publish(NovaEvent(type=EventType.AI_STATUS, agent="Orchestrator",
                                message=f"AI model {status['model']} load ho raha hai...", data=status))
    try:
        await providers.ollama.warm_up()
        message = f"AI model tayyar: {status['model']} ({providers.mode})"
    except httpx.HTTPError as exc:
        message = f"AI model load nahi ho saka ({type(exc).__name__}) — rules fallback rahega"
    await bus.publish(NovaEvent(type=EventType.AI_STATUS, agent="Orchestrator", message=message,
                                data=await providers.status()))


class PermissionDecisionRequest(BaseModel):
    approved: bool
    remember: bool = False


class SecretRequest(BaseModel):
    # Validated by hand in the endpoint: a pydantic error response would echo the secret back.
    value: str


class ContactRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=120)


class MemoryRequest(BaseModel):
    text: str = Field(min_length=1, max_length=memory_facts.MAX_FACT_CHARS)


class WorkflowRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    steps: str = Field(min_length=1, max_length=600)


class RoutineRequest(BaseModel):
    key: str = Field(min_length=3, max_length=800)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=600)


class CommandRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_COMMAND_LENGTH)
    source: str = Field(default="text", pattern="^(text|voice)$")


def create_app(
    settings: Settings | None = None,
    scanner: Callable[[], SystemProfile] | None = None,
    stats: Callable[[], LiveStats] | None = None,
    ollama_transport: httpx.AsyncBaseTransport | None = None,
    stt: SpeechToText | None = None,
    tts: TextToSpeech | None = None,
    desktop: Desktop | None = None,
    browser_controller: BrowserController | None = None,
    web_transport: httpx.AsyncBaseTransport | None = None,
    web_resolver: Callable[..., Any] | None = None,
    known_folders: Callable[[str], Path] | None = None,
    file_overrides: dict[str, Any] | None = None,
    coding_overrides: dict[str, Any] | None = None,
    windows_settings: WindowsSettings | None = None,
    comm_overrides: dict[str, Any] | None = None,
    design_overrides: dict[str, Any] | None = None,
) -> FastAPI:
    """`scanner`/`stats`/`ollama_transport`/`stt`/`tts` replace real collectors, Ollama and voice models (tests).
    `known_folders`/`file_overrides`/`coding_overrides` keep tests away from real folders, the Recycle Bin
    and real commands."""
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.db_path)
        user_settings = load_user_settings(db, default_name=settings.assistant_name)
        assistant_name = user_settings.assistant_name
        bus = EventBus()
        providers = ProviderManager(
            mode=user_settings.ai_mode,
            ollama=OllamaProvider(model=user_settings.ai_model, base_url=settings.ollama_url,
                                  transport=ollama_transport),
        )
        discovery_kwargs: dict[str, Any] = {}
        if scanner:
            discovery_kwargs["scanner"] = scanner
        if stats:
            discovery_kwargs["stats"] = stats
        discovery = DiscoveryService(db, bus, **discovery_kwargs)
        app.state.db = db
        app.state.bus = bus
        app.state.providers = providers
        app.state.discovery = discovery
        computer = ComputerAgent(desktop or Desktop(), lambda: discovery.profile, settings.data_dir / "screenshots")
        permissions = PermissionEngine(db, bus, timeout_s=settings.permission_timeout_s)
        app.state.permissions = permissions
        browser = browser_controller or BrowserController(
            settings.data_dir / "browser-profile",
            downloads_dir=lambda: known_folder("downloads") / "NOVA",
            channel=lambda: app.state.user_settings.browser_channel,
        )
        app.state.browser = browser
        research = ResearchAgent(
            providers.ollama,
            brave_key=lambda: get_secret(db, "brave_api_key"),
            reports_dir=lambda: settings.reports_dir or known_folder("documents") / "NOVA" / "Research",
            transport=web_transport,
            resolver=web_resolver,
        )
        app.state.research = research
        known = known_folders or known_folder
        scope = FileScope(known, project_folders=lambda: app.state.user_settings.project_folders,
                          protected=[PROJECT_ROOT], private=[settings.data_dir])
        app.state.file_scope = scope
        tools_cache: list[Tools] = []

        def tools() -> Tools:
            if not tools_cache:
                tools_cache.append((coding_overrides or {}).get("tools") or find_tools())
            return tools_cache[0]

        def window_titles() -> list[str]:
            return [w.title for w in computer.desktop.list_windows()]

        file_kwargs: dict[str, Any] = {"editor": lambda: tools().code, "window_titles": window_titles}
        file_kwargs.update(file_overrides or {})
        ops = FileOps(scope, db, settings.data_dir / "file-backups",
                      reports_dir=lambda: (settings.reports_dir.parent if settings.reports_dir
                                           else known("documents") / "NOVA") / "Reports",
                      **file_kwargs)
        coding_kwargs: dict[str, Any] = {"window_titles": window_titles}
        coding_kwargs.update({k: v for k, v in (coding_overrides or {}).items() if k != "tools"})
        coding = CodingAgent(scope, ops, providers.ollama.complete_json, providers.ollama.is_available, tools,
                             **coding_kwargs)
        files = FileAgent(ops, scope, projects=coding.find)

        def remember(path: Path) -> None:  # results of other agents become "isko" for the File Agent too
            files.ctx.last_path, files.ctx.last_folder = path, path.parent

        desk = computer.desktop
        comm = comm_overrides or {}
        communication = CommunicationAgent(
            db,
            comm.get("whatsapp") or WhatsAppDesktop(desk.list_windows, desk.focus, desk.foreground_hwnd,
                                                    lambda: desk.hotkey("enter")),
            comm.get("mailer") or Mailer(),
            providers.ollama.complete_json, providers.ollama.is_available,
            resolve_file=files.resolve_target,
        )
        design_kwargs: dict[str, Any] = {"code_exe": lambda: tools().code, "window_titles": window_titles}
        design_kwargs.update(design_overrides or {})
        design = DesignAgent(scope, designs_dir=lambda: known("pictures") / "NOVA" / "Designs",
                             resolve_file=files.resolve_target, remember=remember, **design_kwargs)

        short_term = ShortTermMemory()

        def forget_current_file() -> None:  # "isko" belongs to the conversation that just ended
            files.ctx.last_results, files.ctx.last_path, files.ctx.last_folder = [], None, None

        short_term.on_clear(forget_current_file)

        async def ensure_profile() -> None:
            if discovery.profile is None:
                with contextlib.suppress(Exception):
                    await discovery.run_scan(reason="first_use")

        async def memory_changed(data: dict[str, Any]) -> None:
            if data.get("cleared"):
                bus.clear_history()
            message = {"facts": "Yaadein update hui", "workflows": "Workflows update hue",
                       "history": "History ka ek record mitaya" if data.get("deleted") else "History mitai gayi",
                       "patterns": "Aadatein update hui"}.get(data.get("what", ""), "Memory update hui")
            await bus.publish(NovaEvent(type=EventType.MEMORY_CHANGED, agent=MEMORY_AGENT, message=message, data=data))

        memory = MemoryAgent(
            db, short_term,
            StepResolver(apps=lambda: discovery.profile.apps if discovery.profile else None, projects=coding.find,
                         folder=files.resolve_folder, site_for=site_for),
            ensure_profile=ensure_profile,
            history_days=lambda: app.state.user_settings.history_days,
            notify=memory_changed,
        )
        app.state.memory = memory

        def resolve_app(name: str) -> str | None:  # "chrome" -> "Google Chrome", so habits group correctly
            profile = discovery.profile
            match = find_app(profile.apps, name) if profile else None
            return match.app.name if match else None

        async def save_settings(patch: dict[str, Any]) -> UserSettings:  # "chhote jawab diya karo"
            return await update_settings(UserSettingsUpdate(**patch))

        behavior = BehaviorLayer(db, lambda: app.state.user_settings, save_settings=save_settings,
                                 resolve_app=resolve_app)
        app.state.behavior = behavior
        app.state.orchestrator = Orchestrator(
            bus, db, providers, assistant_name, discovery, computer, permissions,
            browser=BrowserAgent(browser, engine=lambda: app.state.user_settings.search_engine),
            research=research,
            files=files,
            coding=coding,
            settings_agent=SettingsAgent(windows_settings or WindowsSettings(), window_titles=window_titles),
            communication=communication,
            design=design,
            memory=memory,
            behavior=behavior,
        )
        app.state.orchestrator.apply_settings(user_settings.assistant_name, user_settings.wake_word)
        app.state.user_settings = user_settings
        app.state.orchestrator.purge_history(force=True)  # history older than the chosen number of days
        voice = VoiceService(
            bus,
            app.state.orchestrator,
            stt or SpeechToText(settings.models_dir / "whisper", settings.stt_model, user_settings.stt_language),
            tts or TextToSpeech(settings.models_dir / "piper", user_settings.tts_voice),
            settings=lambda: app.state.user_settings,
            permissions=permissions,
        )
        voice.apply_settings(user_settings)
        voice.start_listener()
        app.state.voice = voice
        await bus.publish(
            NovaEvent(type=EventType.SYSTEM_READY, agent="Orchestrator", message=f"{assistant_name} online hai")
        )
        # Refresh the profile in the background on every start (installed apps change); the last
        # stored profile stays available meanwhile.
        startup_scan: asyncio.Task[Any] | None = None
        if settings.discovery_on_startup:
            startup_scan = asyncio.create_task(_background_scan(discovery))
        app.state.background = {asyncio.create_task(_prepare_ai(providers, bus)), asyncio.create_task(voice.prepare())}
        if startup_scan:
            app.state.background.add(startup_scan)
        log.info("NOVA backend ready on %s:%s", settings.host, settings.port)
        try:
            yield
        finally:
            for task in app.state.background:
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            await voice.shutdown()
            await asyncio.to_thread(browser.shutdown)
            db.close()

    app = FastAPI(title="NOVA Backend", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )

    def orchestrator() -> Orchestrator:
        return app.state.orchestrator

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/status")
    async def status() -> dict[str, Any]:
        orch = orchestrator()
        return {
            "assistant_name": orch.assistant_name,
            "state": orch.state.value,
            "version": __version__,
            "ai": await app.state.providers.status(),
            "capabilities": {
                "voice": app.state.voice.stt.model_downloaded() and app.state.voice.tts.is_available(),
                "system_discovery": True,
                "computer_control": True,
                "permission_engine": True,
            },
        }

    @app.get("/api/settings", response_model=UserSettings)
    async def get_settings() -> UserSettings:
        return app.state.user_settings

    @app.put("/api/settings", response_model=UserSettings)
    async def update_settings(update: UserSettingsUpdate) -> UserSettings:
        try:
            new = apply_update(app.state.user_settings, update)
        except ValidationError as exc:
            # Re-raise as a request validation error so the client gets a 422 with field details.
            raise RequestValidationError(exc.errors()) from exc
        known_before = {os.path.normcase(p) for p in app.state.user_settings.project_folders}
        for folder in new.project_folders:
            # Checked only when added: a folder that disappears later must not break loading settings.
            if os.path.normcase(folder) not in known_before and not Path(folder).is_dir():
                raise RequestValidationError([{"loc": ("body", "project_folders"), "msg": f"Folder nahi mila: {folder}",
                                               "type": "value_error"}])
        save_user_settings(app.state.db, new)
        app.state.user_settings = new
        orchestrator().apply_settings(new.assistant_name, new.wake_word)
        app.state.voice.apply_settings(new)
        changed = sorted(k for k, v in update.model_dump(exclude_none=True).items())
        if "history_days" in changed:  # a shorter period applies right away
            orchestrator().purge_history(force=True)
        if {"ai_mode", "ai_model"} & set(changed):
            app.state.providers.configure(mode=new.ai_mode, model=new.ai_model)
            task = asyncio.create_task(_prepare_ai(app.state.providers, app.state.bus))
            app.state.background.add(task)
            task.add_done_callback(app.state.background.discard)
        app.state.db.add_activity(
            task_id="settings", task_name="update_settings", agent="Orchestrator", action="update_settings",
            permission_status="user_initiated", execution_status="success", final_result=", ".join(changed),
        )
        await app.state.bus.publish(
            NovaEvent(type=EventType.SETTINGS_CHANGED, agent="Orchestrator",
                      message=f"Settings update: {', '.join(changed) or 'koi change nahi'}",
                      data=new.model_dump())
        )
        return new

    @app.get("/api/ai/status")
    async def ai_status(refresh: bool = False) -> dict[str, Any]:
        return await app.state.providers.status(refresh=refresh)

    @app.get("/api/permissions/pending")
    async def permissions_pending() -> list[dict[str, Any]]:
        return [{**r.model_dump(), "rememberable": r.rememberable} for r in app.state.permissions.pending]

    @app.post("/api/permissions/{request_id}/decision")
    async def permission_decision(request_id: str, body: PermissionDecisionRequest) -> dict[str, Any]:
        ok = await app.state.permissions.decide(request_id, body.approved, "user_ui", body.remember)
        if not ok:
            raise HTTPException(status_code=404, detail="Ye sawal ab khula nahi (jawab de diya gaya ya waqt khatam)")
        return {"ok": True}

    @app.get("/api/permissions/rules")
    async def permission_rules() -> list[dict[str, Any]]:
        return app.state.db.list_permission_rules()

    @app.delete("/api/permissions/rules/{rule_id}")
    async def delete_permission_rule(rule_id: int) -> dict[str, Any]:
        if not app.state.db.delete_permission_rule(rule_id):
            raise HTTPException(status_code=404, detail="Rule nahi mila")
        app.state.db.add_activity(task_id="permissions", task_name="revoke_rule", agent="Permission Engine",
                                  action="revoke_rule", permission_status="user_initiated",
                                  execution_status="success", final_result=f"rule {rule_id} hataya")
        return {"ok": True}

    @app.get("/api/permissions/history")
    async def permission_history(limit: int = 100) -> list[dict[str, Any]]:
        return app.state.db.list_permission_requests(max(1, min(limit, 500)))

    @app.get("/api/contacts")
    async def contacts() -> list[dict[str, Any]]:
        return app.state.db.list_contacts()

    @app.post("/api/contacts")
    async def add_contact(body: ContactRequest) -> dict[str, Any]:
        name = " ".join(body.name.split())
        phone = normalize_phone(body.phone) if body.phone else None
        email = valid_email(body.email) if body.email else None
        errors = []
        if body.phone and not phone:
            errors.append({"loc": ("body", "phone"), "msg": "Number sahi nahi (maslan 0300 1234567 ya +92 300 1234567)",
                           "type": "value_error"})
        if body.email and not email:
            errors.append({"loc": ("body", "email"), "msg": "Email address sahi nahi", "type": "value_error"})
        if not phone and not email and not errors:
            errors.append({"loc": ("body", "phone"), "msg": "Number ya email zaroori hai", "type": "value_error"})
        if errors:
            raise RequestValidationError(errors)
        row = app.state.db.save_contact(name, phone, email)
        app.state.db.add_activity(task_id="contacts", task_name="save_contact", agent="Communication Agent",
                                  action="save_contact", permission_status="user_initiated",
                                  execution_status="success", final_result=f"contact {name} save hua")
        return row

    @app.delete("/api/contacts/{contact_id}")
    async def remove_contact(contact_id: int) -> dict[str, Any]:
        if not app.state.db.delete_contact(contact_id):
            raise HTTPException(status_code=404, detail="Contact nahi mila")
        app.state.db.add_activity(task_id="contacts", task_name="delete_contact", agent="Communication Agent",
                                  action="delete_contact", permission_status="user_initiated",
                                  execution_status="success", final_result=f"contact {contact_id} hataya")
        return {"ok": True}

    # ------------------------------------------------------------------ memory (the user controls what NOVA keeps)

    def memory_error(field: str, message: str) -> RequestValidationError:
        # Built by hand: the user's text is never echoed back in the error.
        return RequestValidationError([{"loc": ("body", field), "msg": message, "type": "value_error"}])

    def log_memory(action: str, result: str) -> None:
        app.state.db.add_activity(task_id="memory", task_name=action, agent=MEMORY_AGENT, action=action,
                                  permission_status="user_initiated", execution_status="success", final_result=result)

    @app.get("/api/memory/facts")
    async def list_memory_facts() -> list[dict[str, Any]]:
        return app.state.db.list_memories()

    @app.post("/api/memory/facts")
    async def add_memory_fact(body: MemoryRequest) -> dict[str, Any]:
        text = memory_facts.clean(body.text)
        if why := memory_facts.problem(text):
            raise memory_error("text", why)
        fact = memory_facts.to_fact(text)
        if app.state.memory.find_same(fact):
            raise memory_error("text", "Ye pehle se yaad hai")
        row = app.state.db.add_memory(fact.text, "user_ui", fact.slot, fact.value)
        log_memory("remember_fact", f"yaad {row['id']} save hui")
        await app.state.memory.changed("facts")
        return row

    @app.delete("/api/memory/facts/{memory_id}")
    async def delete_memory_fact(memory_id: int) -> dict[str, Any]:
        if not app.state.db.delete_memories([memory_id]):
            raise HTTPException(status_code=404, detail="Ye yaad nahi mili")
        log_memory("forget_memory", f"yaad {memory_id} mitai")
        await app.state.memory.changed("facts")
        return {"ok": True}

    @app.delete("/api/memory/facts")
    async def delete_all_memory_facts() -> dict[str, Any]:
        removed = app.state.db.delete_all_memories()
        log_memory("forget_memory", f"saari {removed} yaadein mitai")
        await app.state.memory.changed("facts")
        return {"ok": True, "removed": removed}

    @app.get("/api/workflows")
    async def list_workflows() -> list[dict[str, Any]]:
        return app.state.db.list_workflows()

    @app.put("/api/workflows")
    async def save_workflow(body: WorkflowRequest) -> dict[str, Any]:
        memory: MemoryAgent = app.state.memory
        name = workflow_key(body.name)
        if not name:
            raise memory_error("name", "Workflow ka naam dein")
        if memory.ensure_profile is not None:
            await memory.ensure_profile()
        steps, problems = await asyncio.to_thread(memory.resolver.resolve_all, body.steps)
        if not steps:
            raise memory_error("steps", "Kuch nahi mila: " + "; ".join(problems))
        if len(steps) > MAX_STEPS:
            raise memory_error("steps", f"Ek workflow mein {MAX_STEPS} cheezon tak ho sakti hain")
        row = app.state.db.save_workflow(name, [s.to_dict() for s in steps])
        log_memory("save_workflow", f"{name}: {len(steps)} cheezein")
        await memory.changed("workflows")
        return {"workflow": row, "problems": problems, "summary": numbered(steps)}

    @app.delete("/api/workflows/{workflow_id}")
    async def delete_workflow(workflow_id: int) -> dict[str, Any]:
        if not app.state.db.delete_workflow(workflow_id):
            raise HTTPException(status_code=404, detail="Workflow nahi mila")
        log_memory("delete_workflow", f"workflow {workflow_id} mitaya")
        await app.state.memory.changed("workflows")
        return {"ok": True}

    @app.get("/api/history")
    async def history(q: str = "", period: str = "", limit: int = 50) -> list[dict[str, Any]]:
        if period not in ("", *PERIODS):
            raise HTTPException(status_code=422, detail="Period sahi nahi")
        return app.state.memory.history(q[:100], "" if period == "all" else period, max(1, min(limit, 200)), raw=True)

    @app.delete("/api/history/{task_id}")
    async def delete_history_entry(task_id: str) -> dict[str, Any]:
        if not app.state.db.delete_task_history(task_id):
            raise HTTPException(status_code=404, detail="Ye record nahi mila")
        await app.state.memory.changed("history", deleted=task_id)
        return {"ok": True}

    @app.delete("/api/history")
    async def delete_all_history() -> dict[str, Any]:
        removed = app.state.db.delete_history()
        app.state.memory.short_term.clear()
        log_memory("clear_history", f"saari history mitai ({removed} baatein)")
        await app.state.memory.changed("history", cleared=True, all=True)
        return {"ok": True, "removed": removed}

    @app.get("/api/behavior/patterns")
    async def behavior_patterns() -> dict[str, Any]:
        return app.state.behavior.patterns()

    @app.delete("/api/behavior/patterns")
    async def forget_patterns() -> dict[str, Any]:
        removed = app.state.db.delete_usage()
        log_memory("forget_patterns", f"aadatein mitai ({removed} records)")
        await app.state.memory.changed("patterns")
        return {"ok": True, "removed": removed}

    @app.post("/api/behavior/routines/decline")
    async def decline_routine(body: RoutineRequest) -> dict[str, Any]:
        app.state.db.decline_routine(body.key)
        await app.state.memory.changed("patterns")
        return {"ok": True}

    @app.get("/api/memory/short-term")
    async def short_term_memory() -> dict[str, Any]:
        return app.state.memory.short_term.snapshot()

    @app.delete("/api/memory/short-term")
    async def clear_short_term_memory() -> dict[str, Any]:
        app.state.memory.short_term.clear()
        await app.state.memory.changed("short_term")
        return {"ok": True}

    @app.get("/api/files/roots")
    async def file_roots() -> list[dict[str, Any]]:
        """Folders the File/Coding agents may use (shown in Settings)."""
        return [{"name": r.name, "path": str(r.path), "kind": r.kind} for r in app.state.file_scope.roots()]

    @app.get("/api/web/status")
    async def web_status() -> dict[str, Any]:
        key = get_secret(app.state.db, "brave_api_key")
        s = app.state.user_settings
        return {
            "search_provider": "brave" if key else "wikipedia",
            "brave_configured": bool(key),
            "brave_key_masked": masked(key),  # never the key itself
            "search_engine": s.search_engine,
            "browser_channel": s.browser_channel,
        }

    @app.put("/api/secrets/{name}")
    async def put_secret(name: str, body: SecretRequest) -> dict[str, Any]:
        if name not in KNOWN_SECRETS:
            raise HTTPException(status_code=404, detail="Unknown secret")
        if not re.fullmatch(r"[A-Za-z0-9_\-.]{8,200}", body.value.strip()):
            raise HTTPException(status_code=422, detail="Key ka format sahi nahi lag raha")
        set_secret(app.state.db, name, body.value.strip())
        app.state.db.add_activity(task_id="settings", task_name="set_secret", agent="Orchestrator",
                                  action="set_secret", permission_status="user_initiated", execution_status="success",
                                  final_result=f"{name} save hui (encrypted)")
        return {"ok": True, "masked": masked(body.value.strip())}

    @app.delete("/api/secrets/{name}")
    async def remove_secret(name: str) -> dict[str, Any]:
        if name not in KNOWN_SECRETS:
            raise HTTPException(status_code=404, detail="Unknown secret")
        delete_secret(app.state.db, name)
        app.state.db.add_activity(task_id="settings", task_name="delete_secret", agent="Orchestrator",
                                  action="delete_secret", permission_status="user_initiated",
                                  execution_status="success", final_result=f"{name} hataya")
        return {"ok": True}

    @app.get("/api/voice/status")
    async def voice_status() -> dict[str, Any]:
        return app.state.voice.status()

    @app.post("/api/voice/speak")
    async def voice_speak(req: SpeakRequest) -> dict[str, Any]:
        """Speak a line through the Urdu voice (used by the 'Awaaz test' button)."""
        voice: VoiceService = app.state.voice
        if not voice.tts.is_available():
            raise HTTPException(status_code=409, detail="Urdu voice download nahi hui")
        return {"speech_id": await voice.speak(req.text)}

    @app.get("/api/voice/speech/{speech_id}")
    async def voice_speech(speech_id: str) -> Response:
        wav = app.state.voice.get_speech(speech_id)
        if wav is None:
            raise HTTPException(status_code=404, detail="Speech expired")
        return Response(content=wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    @app.get("/api/system/profile")
    async def system_profile() -> dict[str, Any]:
        discovery: DiscoveryService = app.state.discovery
        profile = discovery.profile
        return {
            "scanning": discovery.scanning,
            "profile": profile.model_dump(mode="json") if profile else None,
        }

    @app.post("/api/system/scan")
    async def system_scan() -> dict[str, Any]:
        profile = await app.state.discovery.run_scan(reason="api")
        return {"scanned_at": profile.scanned_at, "apps": len(profile.apps), "errors": profile.errors}

    @app.get("/api/system/live", response_model=LiveStats)
    async def system_live() -> LiveStats:
        return await app.state.discovery.live()

    @app.get("/api/system/apps/find")
    async def system_find_app(q: str) -> dict[str, Any]:
        profile = app.state.discovery.profile
        if profile is None:
            return {"match": None, "scanned": False}
        match = find_app(profile.apps, q[:200])
        return {"match": match.model_dump(mode="json") if match else None, "scanned": True}

    @app.post("/api/command", response_model=CommandResult)
    async def command(req: CommandRequest) -> CommandResult:
        return await orchestrator().handle_command(req.text, req.source)

    @app.get("/api/activity")
    async def activity(limit: int = 100) -> list[dict[str, Any]]:
        return app.state.db.list_activity(max(1, min(limit, 500)))

    @app.get("/api/conversations")
    async def conversations(limit: int = 50) -> list[dict[str, Any]]:
        return app.state.db.list_conversations(max(1, min(limit, 500)))

    async def accept_ui_socket(ws: WebSocket) -> bool:
        origin = ws.headers.get("origin")
        # Browsers always send Origin on WebSocket upgrades; reject web pages that are not NOVA's UI.
        if origin is not None and origin not in settings.allowed_origins:
            await ws.close(code=1008)
            return False
        await ws.accept()
        return True

    @app.websocket("/ws/voice")
    async def voice_socket(ws: WebSocket) -> None:
        """Microphone stream: JSON control messages + binary 16 kHz mono int16 PCM frames."""
        if not await accept_ui_socket(ws):
            return
        session = VoiceSession(app.state.voice, ws.send_json)
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if (pcm := msg.get("bytes")) is not None:
                    await session.feed(pcm[:MAX_AUDIO_FRAME_BYTES])
                    continue
                try:
                    control = json.loads(msg.get("text") or "{}")
                except ValueError:
                    continue
                kind = control.get("type")
                if kind == "start":
                    await session.start("continuous" if control.get("mode") == "continuous" else "ptt")
                elif kind == "stop":
                    await session.stop()
        except WebSocketDisconnect:
            pass
        finally:
            await session.close()

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        if not await accept_ui_socket(ws):
            return
        bus: EventBus = app.state.bus
        queue = bus.subscribe()
        orch = orchestrator()
        await ws.send_json(
            {
                "type": "HELLO",
                "data": {
                    "assistant_name": orch.assistant_name,
                    "state": orch.state.value,
                    "version": __version__,
                    "voice_active": orch.voice_active,
                    "settings": app.state.user_settings.model_dump(),
                    "history": [e.model_dump(mode="json") for e in bus.history()[-50:]],
                },
            }
        )

        async def forward_events() -> None:
            while True:
                event = await queue.get()
                await ws.send_json(event.model_dump(mode="json"))

        forwarder = asyncio.create_task(forward_events())
        pending: set[asyncio.Task[Any]] = set()
        client_opened_mic = False
        try:
            while True:
                msg = await ws.receive_json()
                kind = msg.get("type") if isinstance(msg, dict) else None
                if kind == "ping":
                    await ws.send_json({"type": "pong"})
                elif kind == "command":
                    text = str(msg.get("text", "")).strip()[:MAX_COMMAND_LENGTH]
                    if text:
                        source = "voice" if msg.get("source") == "voice" else "text"
                        task = asyncio.create_task(orch.handle_command(text, source))
                        pending.add(task)
                        task.add_done_callback(pending.discard)
                elif kind == "voice_state":
                    client_opened_mic = bool(msg.get("active"))
                    await orch.set_voice_active(client_opened_mic)
                elif kind == "playback":
                    # NOVA's voice is playing in the UI: stop listening so it does not hear itself.
                    app.state.voice.set_playback(bool(msg.get("active")))
                else:
                    await ws.send_json({"type": "ERROR", "message": "Unknown message type"})
        except (WebSocketDisconnect, ValueError):
            pass
        finally:
            bus.unsubscribe(queue)
            # The mic lives in the UI window; if that window goes away the mic is closed too.
            if client_opened_mic:
                with contextlib.suppress(Exception):
                    await orch.set_voice_active(False)
            forwarder.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await forwarder

    return app


app = create_app()
