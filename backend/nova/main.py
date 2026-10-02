"""FastAPI app: local REST API + WebSocket event stream for the NOVA desktop UI."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError

from . import __version__
from .ai.manager import ProviderManager
from .config import Settings, load_settings
from .db import Database
from .discovery import DiscoveryService, LiveStats, SystemProfile, find_app
from .events import EventBus, EventType, NovaEvent
from .orchestrator import CommandResult, Orchestrator
from .user_settings import (
    UserSettings,
    UserSettingsUpdate,
    apply_update,
    load_user_settings,
    save_user_settings,
)

log = logging.getLogger("nova")

MAX_COMMAND_LENGTH = 2000


async def _background_scan(discovery: DiscoveryService) -> None:
    try:
        await discovery.run_scan(reason="startup")
    except Exception:  # already logged and published as DISCOVERY_FAILED
        pass


class CommandRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_COMMAND_LENGTH)
    source: str = Field(default="text", pattern="^(text|voice)$")


def create_app(
    settings: Settings | None = None,
    scanner: Callable[[], SystemProfile] | None = None,
    stats: Callable[[], LiveStats] | None = None,
) -> FastAPI:
    """`scanner`/`stats` override the real Windows collectors (used by tests)."""
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.db_path)
        user_settings = load_user_settings(db, default_name=settings.assistant_name)
        assistant_name = user_settings.assistant_name
        bus = EventBus()
        providers = ProviderManager(active=db.get_setting("ai_provider") or settings.ai_provider)
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
        app.state.orchestrator = Orchestrator(bus, db, providers, assistant_name, discovery)
        app.state.orchestrator.apply_settings(user_settings.assistant_name, user_settings.wake_word)
        app.state.user_settings = user_settings
        await bus.publish(
            NovaEvent(type=EventType.SYSTEM_READY, agent="Orchestrator", message=f"{assistant_name} online hai")
        )
        # Refresh the profile in the background on every start (installed apps change); the last
        # stored profile stays available meanwhile.
        startup_scan: asyncio.Task[Any] | None = None
        if settings.discovery_on_startup:
            startup_scan = asyncio.create_task(_background_scan(discovery))
        log.info("NOVA backend ready on %s:%s", settings.host, settings.port)
        try:
            yield
        finally:
            if startup_scan and not startup_scan.done():
                startup_scan.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await startup_scan
            db.close()

    app = FastAPI(title="NOVA Backend", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST", "PUT"],
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
            "ai_providers": app.state.providers.describe(),
            "capabilities": {
                "voice": False,
                "system_discovery": True,
                "computer_control": False,
                "permission_engine": False,
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
        save_user_settings(app.state.db, new)
        app.state.user_settings = new
        orchestrator().apply_settings(new.assistant_name, new.wake_word)
        changed = sorted(k for k, v in update.model_dump(exclude_none=True).items())
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

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        origin = ws.headers.get("origin")
        # Browsers always send Origin on WebSocket upgrades; reject web pages that are not NOVA's UI.
        if origin is not None and origin not in settings.allowed_origins:
            await ws.close(code=1008)
            return
        await ws.accept()
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
