"""AI Orchestrator: command -> understand (AI brain) -> plan -> agents -> verify -> response.

Low-risk actions run (read-only system info; opening, focusing and arranging windows; reading the
screen) and are verified afterwards. Steps whose agent does not exist yet, or that need permission
(medium/high risk), are planned and reported but never executed; responses never claim otherwise.
The Permission Engine (Phase 7) plugs in at _run_step.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from .agents import system_agent
from .agents.computer import ComputerAgent
from .ai.base import ConversationTurn, Intent
from .ai.manager import ProviderManager
from .db import Database
from .discovery.models import LiveStats, SystemProfile
from .discovery.service import DiscoveryService
from .events import EventBus, EventType, NovaEvent, NovaState
from .planner import Plan, PlanStep, build_plan
from .responses import (
    FALLBACK_NOTES,
    build_error_response,
    build_permission_response,
    build_response,
)

log = logging.getLogger("nova.orchestrator")

ORCHESTRATOR = "Orchestrator"
SYSTEM_INTENTS = {"system_info", "app_check", "rescan_system"}
CONTROL_INTENTS = {"open_app", "focus_app", "window_control", "read_screen", "screenshot", "keyboard_shortcut",
                   "close_app", "type_text", "mouse_click"}
CONTEXT_TURNS = 4  # short-term context for the AI brain; long-term memory is Phase 9


class CommandResult(BaseModel):
    task_id: str
    intent: Intent | None  # first intent (kept for simple clients)
    intents: list[Intent] = []
    plan: list[dict[str, Any]] = []
    provider: str | None = None
    latency_ms: int | None = None
    fallback_reason: str | None = None
    response: str
    status: str  # understood | not_understood | failed
    executed: bool = False  # True only when an agent actually performed a (read-only) action


@dataclass
class AgentOutcome:
    response: str
    agent: str
    action: str
    executed: bool
    verification: str = "not_applicable"  # passed | failed | unverified | not_applicable


class Orchestrator:
    def __init__(
        self,
        bus: EventBus,
        db: Database,
        providers: ProviderManager,
        assistant_name: str,
        discovery: DiscoveryService,
        computer: ComputerAgent | None = None,
    ) -> None:
        self.bus = bus
        self.db = db
        self.providers = providers
        self.assistant_name = assistant_name
        self.discovery = discovery
        self.computer = computer
        self.state = NovaState.IDLE
        self.voice_active = False  # UI microphone is open (level meter only until Phase 5 adds STT)
        self.context: deque[ConversationTurn] = deque(maxlen=CONTEXT_TURNS)

    @property
    def rest_state(self) -> NovaState:
        return NovaState.LISTENING if self.voice_active else NovaState.IDLE

    async def set_state(self, state: NovaState, task_id: str | None = None) -> None:
        self.state = state
        await self.bus.publish(
            NovaEvent(type=EventType.STATE_CHANGED, task_id=task_id, data={"state": state.value})
        )

    def apply_settings(self, assistant_name: str, wake_word: str) -> None:
        self.assistant_name = assistant_name
        self.providers.configure_wake(assistant_name, wake_word)

    async def set_voice_active(self, active: bool) -> None:
        if active == self.voice_active:
            return
        self.voice_active = active
        await self.bus.publish(
            NovaEvent(
                type=EventType.NOVA_LISTENING,
                agent=ORCHESTRATOR,
                message="Microphone on (abhi sirf mic test, awaaz pehchanna Phase 5 mein)" if active else "Microphone off",
                data={"active": active},
            )
        )
        # Only switch the avatar when idle/listening; never interrupt a running task's state.
        if self.state in (NovaState.IDLE, NovaState.LISTENING):
            await self.set_state(self.rest_state)

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
            understanding = await self.providers.understand(text, list(self.context))
            names = ", ".join(i.name for i in understanding.intents)
            await self.bus.publish(
                NovaEvent(
                    type=EventType.INTENT_DETECTED,
                    task_id=task_id,
                    agent=ORCHESTRATOR,
                    message=f"Intent: {names} ({understanding.intents[0].language}) · {understanding.provider} · "
                            f"{understanding.latency_ms} ms",
                    data=understanding.model_dump(),
                )
            )
            if understanding.fallback_reason:
                await self.bus.publish(
                    NovaEvent(type=EventType.AI_FALLBACK, task_id=task_id, agent=ORCHESTRATOR,
                              message=FALLBACK_NOTES.get(understanding.fallback_reason, "Rules fallback"),
                              data={"reason": understanding.fallback_reason})
                )

            await self.set_state(NovaState.PLANNING, task_id)
            plan = build_plan(understanding)
            await self.bus.publish(
                NovaEvent(
                    type=EventType.PLAN_CREATED,
                    task_id=task_id,
                    agent=ORCHESTRATOR,
                    message="Plan: " + " → ".join(f"{s.id}. {s.description}" for s in plan.steps),
                    data={"plan_id": plan.id, "steps": plan.summary()},
                )
            )

            outcomes = [await self._run_step(task_id, step, plan) for step in plan.steps]
        except Exception as exc:  # provider/agent failures must never crash the backend
            log.exception("Command handling failed")
            return await self._fail(task_id, text, source, exc)

        response = self._compose(plan, outcomes)
        primary = plan.steps[0].intent
        status = "not_understood" if all(s.intent.name == "unknown" for s in plan.steps) else "understood"
        self.db.add_conversation(
            task_id=task_id,
            source=source,
            user_text=text,
            detected_language=primary.language,
            intent=",".join(s.intent.name for s in plan.steps),
            response=response,
            status=status,
        )
        self.context.append(ConversationTurn(user=text[:500], assistant=response[:500]))

        await self.bus.publish(
            NovaEvent(
                type=EventType.NOVA_RESPONSE,
                task_id=task_id,
                agent=ORCHESTRATOR,
                message=response,
                data={"response": response, "intent": primary.name, "steps": plan.summary(),
                      "provider": plan.provider, "source": source},
            )
        )
        await self.bus.publish(
            NovaEvent(type=EventType.TASK_COMPLETED, task_id=task_id, agent=ORCHESTRATOR, message="Task mukammal")
        )
        await self.set_state(NovaState.COMPLETED, task_id)
        await self.set_state(self.rest_state)
        return CommandResult(
            task_id=task_id,
            intent=primary,
            intents=[s.intent for s in plan.steps],
            plan=plan.summary(),
            provider=plan.provider,
            latency_ms=understanding.latency_ms,
            fallback_reason=plan.fallback_reason,
            response=response,
            status=status,
            executed=any(o.executed for o in outcomes),
        )

    async def _run_step(self, task_id: str, step: PlanStep, plan: Plan) -> AgentOutcome:
        intent = step.intent
        if intent.name in SYSTEM_INTENTS and step.status in ("ready", "unavailable"):
            # open_app is "unavailable" for launching, but the System Agent can still say whether it exists.
            outcome = await self._run_system_agent(task_id, intent)
        elif intent.name in CONTROL_INTENTS and step.status == "ready":
            if self.computer is None:
                outcome = AgentOutcome("Computer control is PC par available nahi.", step.agent, step.action, False)
            else:
                outcome = await self._run_computer(task_id, step)
        elif step.status == "needs_permission":
            # Medium/high risk: never executed without the user's permission (Permission Engine, Phase 7).
            outcome = AgentOutcome(build_permission_response(intent, step.description), step.agent, step.action,
                                   executed=False)
        else:
            outcome = AgentOutcome(build_response(intent, self.assistant_name, plan.answer), step.agent,
                                   step.action, executed=False)
            if intent.name == "chat" and plan.answer:
                # The answer was written by the local model; only words, nothing executed on the PC.
                outcome = AgentOutcome(outcome.response, ORCHESTRATOR, "answer_question", executed=False)

        step.result = outcome.response
        if step.status == "ready":
            step.status = "done"
        execution = {
            "done": "success" if outcome.executed else "responded",
            "unavailable": "not_available_yet",
            "needs_permission": "blocked_needs_permission",
        }.get(step.status, step.status)
        self.db.add_activity(
            task_id=task_id,
            task_name=f"command:{intent.name}",
            agent=outcome.agent,
            action=outcome.action,
            permission_status="required_pending" if step.status == "needs_permission" else "not_required",
            execution_status=execution,
            # Read-only lookups change nothing on the PC, so there is no state to verify afterwards.
            verification_status=outcome.verification,
            final_result=f"step {step.id}/{len(plan.steps)} · risk {step.risk} · {plan.provider}",
        )
        await self.bus.publish(
            NovaEvent(
                type=EventType.STEP_COMPLETED,
                task_id=task_id,
                agent=outcome.agent,
                message=f"Step {step.id}: {step.description} — {execution.replace('_', ' ')}",
                data={"step": step.id, "status": step.status, "execution": execution, "risk": step.risk},
            )
        )
        return outcome

    async def _run_computer(self, task_id: str, step: PlanStep) -> AgentOutcome:
        """Run a computer-control action and report its verification (spec: never assume success)."""
        assert self.computer is not None
        if step.intent.name in ("open_app", "focus_app", "window_control", "close_app"):
            await self._ensure_profile(task_id)  # app names are resolved through the discovered catalog
        await self.set_state(NovaState.WORKING, task_id)
        await self.bus.publish(NovaEvent(type=EventType.AGENT_STARTED, task_id=task_id, agent=step.agent,
                                         message=f"{step.description}..."))
        result = await asyncio.to_thread(self.computer.run, step.intent)
        if result.executed:
            await self.bus.publish(NovaEvent(type=EventType.ACTION_EXECUTED, task_id=task_id, agent=step.agent,
                                             message=f"Action: {result.action}", data={"action": result.action}))
        if result.verification in ("passed", "failed"):
            await self.set_state(NovaState.VERIFYING, task_id)
            await self.bus.publish(NovaEvent(type=EventType.VERIFICATION_STARTED, task_id=task_id, agent=step.agent,
                                             message="Nateeja verify kar raha hai"))
            passed = result.verification == "passed"
            await self.bus.publish(
                NovaEvent(type=EventType.VERIFICATION_PASSED if passed else EventType.VERIFICATION_FAILED,
                          task_id=task_id, agent=step.agent,
                          message=("Verify ho gaya" if passed else "Verify nahi ho saka") +
                                  (f": {result.detail}" if result.detail else ""),
                          data={"action": result.action})
            )
        return AgentOutcome(result.response, step.agent, result.action, executed=result.executed,
                            verification=result.verification)

    def _compose(self, plan: Plan, outcomes: list[AgentOutcome]) -> str:
        if len(outcomes) == 1:
            text = outcomes[0].response
        else:
            lines = [f"Aapne {len(outcomes)} kaam bataye:"]
            lines += [f"{n}. {o.response}" for n, o in enumerate(outcomes, start=1)]
            text = "\n".join(lines)
        # Mention the fallback only when it could have changed the answer (unclear text or a question).
        if plan.fallback_reason and plan.steps[0].intent.name in ("unknown", "chat"):
            text += f"\n({FALLBACK_NOTES.get(plan.fallback_reason, '')})"
        return text

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

        if profile is None:
            return AgentOutcome("System scan abhi mukammal nahi ho saka. Thori der baad dobara poochiye.",
                                agent, "read_profile", executed=False)

        if intent.name == "app_check":
            if not app:
                return AgentOutcome("Kaun si application check karni hai?", agent, "app_lookup", executed=False)
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
        await self.set_state(self.rest_state)
        return CommandResult(task_id=task_id, intent=None, response=response, status="failed")
