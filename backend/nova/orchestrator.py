"""AI Orchestrator: command -> intent -> (future: plan, permission, agent, verify) -> response.

Phase 1 only detects intent and responds. It never claims an action was executed, because
no execution agents exist yet.
"""

from __future__ import annotations

import logging
import uuid

from pydantic import BaseModel

from .ai.base import Intent
from .ai.manager import ProviderManager
from .db import Database
from .events import EventBus, EventType, NovaEvent, NovaState
from .responses import build_error_response, build_response

log = logging.getLogger("nova.orchestrator")

ORCHESTRATOR = "Orchestrator"


class CommandResult(BaseModel):
    task_id: str
    intent: Intent | None
    response: str
    status: str  # understood | not_understood | failed
    executed: bool = False


class Orchestrator:
    def __init__(self, bus: EventBus, db: Database, providers: ProviderManager, assistant_name: str) -> None:
        self.bus = bus
        self.db = db
        self.providers = providers
        self.assistant_name = assistant_name
        self.state = NovaState.IDLE

    async def set_state(self, state: NovaState, task_id: str | None = None) -> None:
        self.state = state
        await self.bus.publish(
            NovaEvent(type=EventType.STATE_CHANGED, task_id=task_id, data={"state": state.value})
        )

    async def handle_command(self, text: str, source: str = "text") -> CommandResult:
        task_id = uuid.uuid4().hex[:12]
        text = text.strip()
        await self.bus.publish(
            NovaEvent(
                type=EventType.TASK_STARTED,
                task_id=task_id,
                agent=ORCHESTRATOR,
                message="Command receive hui",
                data={"text": text, "source": source},
            )
        )
        await self.set_state(NovaState.THINKING, task_id)
        await self.bus.publish(
            NovaEvent(type=EventType.NOVA_THINKING, task_id=task_id, agent=ORCHESTRATOR, message="Command samajh raha hai")
        )

        try:
            intent = await self.providers.detect_intent(text)
        except Exception as exc:  # provider failures must never crash the backend
            log.exception("Intent detection failed")
            return await self._fail(task_id, text, source, exc)

        await self.bus.publish(
            NovaEvent(
                type=EventType.INTENT_DETECTED,
                task_id=task_id,
                agent=ORCHESTRATOR,
                message=f"Intent: {intent.name} ({intent.language})",
                data=intent.model_dump(),
            )
        )

        response = build_response(intent, self.assistant_name)
        status = "not_understood" if intent.name == "unknown" else "understood"

        self.db.add_conversation(
            task_id=task_id,
            source=source,
            user_text=text,
            detected_language=intent.language,
            intent=intent.name,
            response=response,
            status=status,
        )
        self.db.add_activity(
            task_id=task_id,
            task_name=f"command:{intent.name}",
            agent=ORCHESTRATOR,
            action="intent_detection",
            execution_status="intent_only",  # no execution agents in Phase 1
            final_result=status,
        )

        await self.bus.publish(
            NovaEvent(
                type=EventType.NOVA_RESPONSE,
                task_id=task_id,
                agent=ORCHESTRATOR,
                message=response,
                data={"response": response, "intent": intent.name},
            )
        )
        await self.bus.publish(
            NovaEvent(type=EventType.TASK_COMPLETED, task_id=task_id, agent=ORCHESTRATOR, message="Task mukammal")
        )
        await self.set_state(NovaState.COMPLETED, task_id)
        await self.set_state(NovaState.IDLE)
        return CommandResult(task_id=task_id, intent=intent, response=response, status=status)

    async def _fail(self, task_id: str, text: str, source: str, exc: Exception) -> CommandResult:
        response = build_error_response()
        self.db.add_conversation(
            task_id=task_id, source=source, user_text=text, detected_language=None,
            intent=None, response=response, status="failed",
        )
        self.db.add_activity(
            task_id=task_id, task_name="command", agent=ORCHESTRATOR, action="intent_detection",
            execution_status="failed", error=f"{type(exc).__name__}: {exc}", final_result="failed",
        )
        await self.bus.publish(
            NovaEvent(type=EventType.TASK_FAILED, task_id=task_id, agent=ORCHESTRATOR, message=response,
                      data={"error": type(exc).__name__})
        )
        await self.set_state(NovaState.ERROR, task_id)
        await self.set_state(NovaState.IDLE)
        return CommandResult(task_id=task_id, intent=None, response=response, status="failed")
