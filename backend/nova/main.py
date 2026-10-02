"""FastAPI app: local REST API + WebSocket event stream for the NOVA desktop UI."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import __version__
from .ai.manager import ProviderManager
from .config import Settings, load_settings
from .db import Database
from .events import EventBus, EventType, NovaEvent
from .orchestrator import CommandResult, Orchestrator

log = logging.getLogger("nova")

MAX_COMMAND_LENGTH = 2000


class CommandRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_COMMAND_LENGTH)
    source: str = Field(default="text", pattern="^(text|voice)$")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.db_path)
        assistant_name = db.get_setting("assistant_name") or settings.assistant_name
        bus = EventBus()
        providers = ProviderManager(active=db.get_setting("ai_provider") or settings.ai_provider)
        app.state.db = db
        app.state.bus = bus
        app.state.providers = providers
        app.state.orchestrator = Orchestrator(bus, db, providers, assistant_name)
        await bus.publish(
            NovaEvent(type=EventType.SYSTEM_READY, agent="Orchestrator", message=f"{assistant_name} online hai")
        )
        log.info("NOVA backend ready on %s:%s", settings.host, settings.port)
        try:
            yield
        finally:
            db.close()

    app = FastAPI(title="NOVA Backend", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST"],
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
                "system_discovery": False,
                "computer_control": False,
                "permission_engine": False,
            },
        }

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
                else:
                    await ws.send_json({"type": "ERROR", "message": "Unknown message type"})
        except (WebSocketDisconnect, ValueError):
            pass
        finally:
            bus.unsubscribe(queue)
            forwarder.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await forwarder

    return app


app = create_app()
