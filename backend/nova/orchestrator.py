"""AI Orchestrator: command -> intent -> agent -> response (future phases add plan, permission, verify).

Only read-only System Agent actions execute in Phase 2. Nothing else is executed, and responses
never claim otherwise.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from pydantic import BaseModel

from .agents import system_agent
from .ai.base import Intent
from .ai.manager import ProviderManager
from .db import Database
from .discovery.models import LiveStats, SystemProfile
from .discovery.service import DiscoveryService
from .events import EventBus, EventType, NovaEvent, NovaState
from .responses import PENDING_CAPABILITY_PHASE, build_error_response, build_response

log = logging.getLogger("nova.orchestrator")

ORCHESTRATOR = "Orchestrator"
SYSTEM_INTENTS = {"system_info", "app_check", "rescan_system", "open_app"}


class CommandResult(BaseModel):
    task_id: str
    intent: Intent | None
    response: str
    status: str  # understood | not_understood | failed
    executed: bool = False  # True only when an agent actually performed a (read-only) action


@dataclass
class AgentOutcome:
    response: str
    agent: str
    action: str
    executed: bool


class Orchestrator:
    def __init__(
        self,
        bus: EventBus,
        db: Database,
        providers: ProviderManager,
        assistant_name: str,
        discovery: DiscoveryService,
    ) -> None:
        self.bus = bus
        self.db = db
        self.providers = providers
        self.assistant_name = assistant_name
        self.discovery = discovery
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
            await self.bus.publish(
                NovaEvent(
                    type=EventType.INTENT_DETECTED,
                    task_id=task_id,
                    agent=ORCHESTRATOR,
                    message=f"Intent: {intent.name} ({intent.language})",
                    data=intent.model_dump(),
                )
            )
            if intent.name in SYSTEM_INTENTS:
                outcome = await self._run_system_agent(task_id, intent)
            else:
                outcome = AgentOutcome(build_response(intent, self.assistant_name), ORCHESTRATOR,
                                       "intent_detection", executed=False)
        except Exception as exc:  # provider/agent failures must never crash the backend
            log.exception("Command handling failed")
            return await self._fail(task_id, text, source, exc)

        status = "not_understood" if intent.name == "unknown" else "understood"
        self.db.add_conversation(
            task_id=task_id,
            source=source,
            user_text=text,
            detected_language=intent.language,
            intent=intent.name,
            response=outcome.response,
            status=status,
        )
        self.db.add_activity(
            task_id=task_id,
            task_name=f"command:{intent.name}",
            agent=outcome.agent,
            action=outcome.action,
            execution_status="success" if outcome.executed else "intent_only",
            # Read-only lookups change nothing on the PC, so there is no state to verify afterwards.
            verification_status="not_applicable",
            final_result=status,
        )

        await self.bus.publish(
            NovaEvent(
                type=EventType.NOVA_RESPONSE,
                task_id=task_id,
                agent=ORCHESTRATOR,
                message=outcome.response,
                data={"response": outcome.response, "intent": intent.name},
            )
        )
        await self.bus.publish(
            NovaEvent(type=EventType.TASK_COMPLETED, task_id=task_id, agent=ORCHESTRATOR, message="Task mukammal")
        )
        await self.set_state(NovaState.COMPLETED, task_id)
        await self.set_state(NovaState.IDLE)
        return CommandResult(task_id=task_id, intent=intent, response=outcome.response, status=status,
                             executed=outcome.executed)

    async def _run_system_agent(self, task_id: str, intent: Intent) -> AgentOutcome:
        agent = system_agent.NAME
        await self.set_state(NovaState.WORKING, task_id)
        await self.bus.publish(
            NovaEvent(type=EventType.AGENT_STARTED, task_id=task_id, agent=agent, message="System maloomat parh raha hai")
        )

        if intent.name == "rescan_system":
            profile = await self.discovery.run_scan(reason="user_command")
            response = (f"System dobara scan ho gaya ({profile.scan_duration_ms / 1000:.1f}s). "
                        f"{len(profile.apps)} applications detect hui hain.")
            if profile.errors:
                response += f" {len(profile.errors)} cheezein detect nahi ho sakin."
            return await self._executed(task_id, agent, "rescan", response)

        profile = await self._ensure_profile(task_id)
        app = str(intent.entities.get("app") or "")

        if intent.name == "open_app":
            response = system_agent.describe_open_app(app, profile, PENDING_CAPABILITY_PHASE["open_app"])
            return AgentOutcome(response, agent, "app_lookup", executed=False)  # nothing was launched

        if profile is None:
            return AgentOutcome("System scan abhi mukammal nahi ho saka. Thori der baad dobara poochiye.",
                                agent, "read_profile", executed=False)

        if intent.name == "app_check":
            response, _found = system_agent.describe_app(app, profile)
            return await self._executed(task_id, agent, "app_lookup", response)

        topic = str(intent.entities.get("topic") or "summary")
        live: LiveStats | None = None
        if topic in ("summary", "cpu", "ram", "storage"):
            live = await self.discovery.live()
        return await self._executed(task_id, agent, f"read_system_info:{topic}",
                                    system_agent.describe(topic, profile, live))

    async def _executed(self, task_id: str, agent: str, action: str, response: str) -> AgentOutcome:
        await self.bus.publish(
            NovaEvent(type=EventType.ACTION_EXECUTED, task_id=task_id, agent=agent,
                      message=f"Read-only action: {action}", data={"action": action, "read_only": True})
        )
        return AgentOutcome(response, agent, action, executed=True)

    async def _ensure_profile(self, task_id: str) -> SystemProfile | None:
        if self.discovery.profile is not None:
            return self.discovery.profile
        await self.bus.publish(
            NovaEvent(type=EventType.AGENT_WORKING, task_id=task_id, agent=system_agent.NAME,
                      message="Pehli dafa system scan kar raha hai")
        )
        try:
            return await self.discovery.run_scan(reason="first_use")
        except Exception:
            return None

    async def _fail(self, task_id: str, text: str, source: str, exc: Exception) -> CommandResult:
        response = build_error_response()
        self.db.add_conversation(
            task_id=task_id, source=source, user_text=text, detected_language=None,
            intent=None, response=response, status="failed",
        )
        self.db.add_activity(
            task_id=task_id, task_name="command", agent=ORCHESTRATOR, action="handle_command",
            execution_status="failed", error=f"{type(exc).__name__}: {exc}", final_result="failed",
        )
        await self.bus.publish(
            NovaEvent(type=EventType.TASK_FAILED, task_id=task_id, agent=ORCHESTRATOR, message=response,
                      data={"error": type(exc).__name__})
        )
        await self.set_state(NovaState.ERROR, task_id)
        await self.set_state(NovaState.IDLE)
        return CommandResult(task_id=task_id, intent=None, response=response, status="failed")
