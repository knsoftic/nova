"""AI Orchestrator: command -> understand -> plan -> permission -> agents -> verify -> response.

Low-risk actions run directly. Medium/high-risk steps go through the Permission Engine first: the
user is asked (or a remembered approval for exactly that action applies) and only approved steps
run. Steps whose agent does not exist yet are planned and reported but never executed; responses
never claim an action that did not happen.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from .agents import system_agent
from .agents.computer import ComputerAgent, ControlOutcome
from .agents.file_agent import FILE_INTENTS, FileAgent
from .agents.prepared import Prepared, Reply
from .ai.base import Intent, Understanding
from .agents.settings_agent import SETTINGS_INTENTS
from .coding import CODING_INTENTS, CodingAgent
from .communication import COMM_INTENTS
from .design import DESIGN_INTENTS
from .files import ScopeError
from .browser.agent import BrowserAgent, download_is_executable, site_for
from .browser.controller import ElementInfo
from .ai.manager import ProviderManager
from .db import Database
from .discovery.apps import find_app
from .discovery.models import LiveStats, SystemProfile
from .discovery.service import DiscoveryService
from .events import EventBus, EventType, NovaEvent, NovaState
from .behavior.estimator import Estimate
from .behavior.layer import BEHAVIOR_INTENTS, BehaviorLayer
from .behavior.layer import NAME as BEHAVIOR
from .behavior.patterns import OPEN_KINDS
from .behavior.signals import VoiceFeatures
from .language import detect_language
from .memory.agent import MEMORY_INTENTS, MemoryAgent
from .memory.agent import NAME as MEMORY
from .memory.short_term import ShortTermMemory
from .multipc import MULTIPC_INTENTS
from .multipc.policy import ALLOWED as REMOTE_ALLOWED
from .multipc.policy import REFUSED as REMOTE_REFUSED
from .multipc.policy import verdict as remote_verdict
from .permissions import PermissionEngine, TargetContext
from .permissions.engine import classify
from .planner import Plan, PlanStep, build_plan
from .research import ResearchAgent, SearchError
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
BROWSER_INTENTS = {"open_website", "web_search", "read_page", "browser_nav", "browser_click", "browser_type",
                   "download"}
RESEARCH_INTENTS = {"research", "web_answer"}
# Safe to try once more by itself when verification fails: opening, showing, reading, a fixed level (spec 32).
# Sending, deleting, typing, clicking or anything the user had to approve is never repeated on its own.
SAFE_RETRY = {"open_app", "focus_app", "window_control", "open_website", "read_page", "open_project", "open_file",
              "change_setting"}
REMOTE_PLAN_TTL_S = 180  # a paired PC's plan must be run (or dropped) within this time


def is_approved(step: PlanStep) -> bool:
    """Approved by the user here, by a remembered rule, or (a paired PC's task) by the user on that PC."""
    return step.permission in ("approved", "rule", "remote")


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
    test_status: str = "not_run"  # passed | failed when the step ran a project's tests


class Orchestrator:
    def __init__(
        self,
        bus: EventBus,
        db: Database,
        providers: ProviderManager,
        assistant_name: str,
        discovery: DiscoveryService,
        computer: ComputerAgent | None = None,
        permissions: PermissionEngine | None = None,
        browser: BrowserAgent | None = None,
        research: ResearchAgent | None = None,
        files: FileAgent | None = None,
        coding: CodingAgent | None = None,
        settings_agent: Any = None,
        communication: Any = None,
        design: Any = None,
        memory: MemoryAgent | None = None,
        short_term: ShortTermMemory | None = None,
        behavior: BehaviorLayer | None = None,
        multipc: Any = None,
    ) -> None:
        self.permissions = permissions
        self.browser = browser
        self.research = research
        self.files = files
        self.coding = coding
        # Agents with the common async protocol: prepare(intent, progress) -> Prepared | Reply,
        # run(intent, prepared, approved, progress) -> ControlOutcome.
        self.prepared_agents: dict[str, Any] = {}
        for agent, intents in ((settings_agent, SETTINGS_INTENTS), (communication, COMM_INTENTS),
                               (design, DESIGN_INTENTS), (memory, MEMORY_INTENTS), (behavior, BEHAVIOR_INTENTS),
                               (multipc, MULTIPC_INTENTS)):
            if agent is not None:
                self.prepared_agents.update(dict.fromkeys(intents, agent))
        self.bus = bus
        self.db = db
        self.providers = providers
        self.assistant_name = assistant_name
        self.discovery = discovery
        self.computer = computer
        self.state = NovaState.IDLE
        self.voice_active = False  # UI microphone is open (level meter only until Phase 5 adds STT)
        self.memory = memory
        # Short-term memory: the current conversation (context for the AI brain, "dobara karo", open questions).
        self.short_term = short_term or (memory.short_term if memory is not None else ShortTermMemory())
        # Behavior layer: an estimate of how the user is communicating (RAM only) -> NOVA's tone; habits.
        self.behavior = behavior
        # Multi-PC: "<paired PC> par ..." is recognised before the AI brain, so it can never run here by mistake.
        self.multipc = multipc
        self._remote_plans: dict[str, tuple[Plan, str, str, str, float]] = {}  # plans a paired PC asked for
        # Set by the app: a crash while handling a command becomes a bug in the bug tracker (Phase 11).
        self.on_crash: Callable[[BaseException, str], Awaitable[Any]] | None = None
        if behavior is not None:
            self.short_term.on_clear(behavior.estimator.forget_mood)

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
                message="Microphone on — sun raha hoon" if active else "Microphone off",
                data={"active": active},
            )
        )
        # Only switch the avatar when idle/listening; never interrupt a running task's state.
        if self.state in (NovaState.IDLE, NovaState.LISTENING):
            await self.set_state(self.rest_state)

    async def handle_command(self, text: str, source: str = "text", voice: VoiceFeatures | None = None) -> CommandResult:
        task_id = uuid.uuid4().hex[:12]
        text = text.strip()
        # "haan" / "nahi" while NOVA is waiting for permission answers that question, it is not a new command.
        if self.permissions is not None:
            answer = await self.permissions.answer_latest(text, f"user_{source}")
            if answer is not None:
                return CommandResult(task_id=task_id, intent=None, status="permission_answer",
                                     response="Theek hai." if answer else "Theek hai, ye kaam nahi karunga.")
        if self.computer is not None:
            self.computer.note_command(source)  # the window hosting NOVA's UI is never a target
        self.short_term.touch()
        asked_before = self.short_term.pending
        # How the user seems to be communicating (an estimate) decides the tone of the reply.
        estimate = (self.behavior.estimate(text, self.short_term.recent(), voice) if self.behavior is not None
                    else Estimate())
        style = self.behavior.style(estimate) if self.behavior is not None else "normal"
        await self.bus.publish(
            NovaEvent(
                type=EventType.TASK_STARTED,
                task_id=task_id,
                agent=ORCHESTRATOR,
                message="Command receive hui",
                data={"text": text, "source": source},
            )
        )
        await self._publish_estimate(task_id, estimate, style)
        await self.set_state(NovaState.THINKING, task_id)
        await self.bus.publish(
            NovaEvent(type=EventType.NOVA_THINKING, task_id=task_id, agent=ORCHESTRATOR, message="Command samajh raha hai")
        )

        repeated: str | None = None
        try:
            # An answer to NOVA's own question ("Ye yaad rakhoon?" -> "haan") is not a new command.
            followup = await self.memory.answer(text, detect_language(text)) if self.memory is not None else None
            if followup is not None and followup.reply is not None:
                return await self._reply_only(task_id, text, source, followup.reply, asked_before)
            if followup is not None:
                understanding = Understanding(intents=followup.intents, provider="memory")
            else:
                memories = self.memory.context_for(text) if self.memory is not None else None
                hint = self.behavior.llm_hint(style) if self.behavior is not None else None
                understanding = await self._understand(text, memories, hint)
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
            understanding = await self._route(understanding)
            understanding, workflow, repeated = await self._expand(task_id, understanding)
            plan = build_plan(understanding)
            plan.workflow = workflow or (followup.workflow if followup is not None else None)
            await self.bus.publish(
                NovaEvent(
                    type=EventType.PLAN_CREATED,
                    task_id=task_id,
                    agent=ORCHESTRATOR,
                    message="Plan: " + " → ".join(f"{s.id}. {s.description}" for s in plan.steps),
                    data={"plan_id": plan.id, "steps": plan.summary()},
                )
            )

            await self._prepare_steps(task_id, plan)
            await self._seek_permission(task_id, plan, source)
            outcomes = []
            for step in plan.steps:
                outcome = await self._run_step(task_id, step, plan)
                if self._may_retry(step, outcome):
                    outcome = await self._retry_step(task_id, step, plan)
                outcomes.append(outcome)
        except Exception as exc:  # provider/agent failures must never crash the backend
            log.exception("Command handling failed")
            return await self._fail(task_id, text, source, exc)

        response = self._compose(plan, outcomes)
        primary = plan.steps[0].intent
        status = "not_understood" if all(s.intent.name == "unknown" for s in plan.steps) else "understood"
        outcome = self._outcome(status, plan, outcomes)
        speech: str | None = None
        if self.behavior is not None:
            response, speech = self.behavior.shape(response, style, outcome=outcome, simple=estimate.simple,
                                                   intents=[s.intent.name for s in plan.steps])
            response, speech = self._learn(task_id, plan, outcomes, response, speech)
        self.db.add_conversation(
            task_id=task_id,
            source=source,
            user_text=text,
            detected_language=primary.language,
            intent=",".join(s.intent.name for s in plan.steps),
            response=response,
            status=status,
        )
        # "dobara karo" repeats the last real command: not answers or repeats, and not plain statements or questions
        # (only something that ran, or that the user may want to retry after saying no).
        is_command = (followup is None and repeated is None and primary.name != "repeat_last"
                      and any(o.executed or s.status == "denied" for s, o in zip(plan.steps, outcomes)))
        self.short_term.add_turn(text, response, command=is_command, outcome=outcome)
        shown = self.behavior is not None and self.behavior.settings().show_estimate and estimate.state != "neutral"
        await self._finish(task_id, source, response, asked_before,
                           {"intent": primary.name, "steps": plan.summary(), "provider": plan.provider,
                            "speech": speech, "style": style, "estimate": estimate.to_dict() if shown else None})
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

    async def _understand(self, text: str, memories: list[str] | None = None, hint: str | None = None) -> Understanding:
        if self.multipc is not None and (remote := self.multipc.understand(self.providers.rules.clean(text))):
            return remote
        return await self.providers.understand(text, self.short_term.turns(), memories, hint)

    async def _finish(self, task_id: str, source: str, response: str, asked_before: Any, data: dict[str, Any]) -> None:
        """Publish the reply (and whether NOVA now waits for an answer to its own question) and close the task."""
        asked = self.short_term.pending
        awaiting = asked is not None and asked is not asked_before
        await self.bus.publish(
            NovaEvent(
                type=EventType.NOVA_RESPONSE,
                task_id=task_id,
                agent=ORCHESTRATOR,
                message=response,
                data={"response": response, "source": source, "awaiting_answer": awaiting,
                      "quick_replies": ["Haan", "Nahi"] if awaiting and asked.kind in ("remember", "routine", "retry")
                      else [],
                      **data},
            )
        )
        await self.bus.publish(
            NovaEvent(type=EventType.TASK_COMPLETED, task_id=task_id, agent=ORCHESTRATOR, message="Task mukammal")
        )
        await self.set_state(NovaState.COMPLETED, task_id)
        await self.set_state(self.rest_state)
        self.purge_history()

    def purge_history(self, force: bool = False) -> int:
        """History older than the user's chosen number of days is deleted (checked at most once an hour)."""
        removed = self.memory.purge(force=force) if self.memory is not None else 0
        if removed:
            self.db.add_activity(task_id="memory", task_name="history_retention", agent=MEMORY, action="purge_history",
                                 permission_status="user_setting", execution_status="success",
                                 final_result=f"{removed} purani baatein mitai gayin")
        return removed

    @staticmethod
    def _outcome(status: str, plan: Plan, outcomes: list[AgentOutcome]) -> str:
        """done | failed | denied | answered | not_understood - how the request ended (for the estimate)."""
        if status == "not_understood":
            return "not_understood"
        if any(o.verification == "failed" for o in outcomes) or any(s.status == "failed" for s in plan.steps):
            return "failed"
        if any(o.executed for o in outcomes):
            return "done"
        if any(s.status == "denied" for s in plan.steps):
            return "denied"
        return "answered"

    async def _publish_estimate(self, task_id: str, estimate: Estimate, style: str) -> None:
        if self.behavior is None or estimate.state == "neutral" or not self.behavior.settings().show_estimate:
            return
        tone = {"calm": "jawab chhota aur pur-sukoon", "brief": "jawab chhota", "helpful": "jawab misaal ke sath",
                "detailed": "jawab tafseel se"}.get(style, "jawab aam andaz mein")
        await self.bus.publish(NovaEvent(
            type=EventType.BEHAVIOR_ESTIMATED, task_id=task_id, agent=BEHAVIOR,
            message=f"Andaza (sirf andaza): {estimate.label} — {', '.join(estimate.reasons)}. {tone.capitalize()}.",
            data={**estimate.to_dict(), "style": style}))

    def _learn(self, task_id: str, plan: Plan, outcomes: list[AgentOutcome], response: str,
               speech: str | None) -> tuple[str, str | None]:
        """Remember what ran (habits); when a routine shows up, ask once whether to make it a workflow."""
        assert self.behavior is not None
        opened = False
        for step, outcome in zip(plan.steps, outcomes):
            if outcome.executed and outcome.verification != "failed":
                self.behavior.record(task_id, step.intent)
                opened = opened or step.intent.name in OPEN_KINDS
        if not opened or self.short_term.pending is not None or plan.workflow:
            return response, speech
        routine = self.behavior.routine_to_suggest()
        if routine is None:
            return response, speech
        name = self.behavior.routine_name(routine)
        question = self.behavior.suggestion(routine, name)
        self.short_term.ask("routine", question, {"name": name, "steps": ", ".join(routine.labels), "key": routine.key},
                            ttl_s=300)
        self.behavior.suggested = True
        return f"{response}\n\n{question}", (f"{speech} {question}" if speech else None)

    async def _reply_only(self, task_id: str, text: str, source: str, response: str, asked_before: Any) -> CommandResult:
        """NOVA's question was answered with a plain reply ("nahi" -> "Theek hai, yaad nahi rakha")."""
        self.db.add_conversation(task_id=task_id, source=source, user_text=text, detected_language=detect_language(text),
                                 intent="followup", response=response, status="understood")
        self.db.add_activity(task_id=task_id, task_name="command:followup", agent=MEMORY, action="answer_question",
                             execution_status="responded", final_result="sawal ka jawab")
        self.short_term.add_turn(text, response, command=False, outcome="answered")
        await self._finish(task_id, source, response, asked_before, {"intent": "followup", "steps": [],
                                                                     "provider": "memory"})
        return CommandResult(task_id=task_id, intent=None, response=response, status="understood")

    async def _expand(self, task_id: str, understanding: Understanding,
                      repeats: bool = True) -> tuple[Understanding, str | None, str | None]:
        """A saved workflow becomes its steps; "dobara karo" becomes the last command again. Both then go through
        the normal plan, permission and verification like any other command."""
        requested: list[Intent] = []
        workflow = repeated = None
        for intent in understanding.intents:
            if (repeats and intent.name == "repeat_last" and intent.entities.get("what") != "response" and repeated is None
                    and (last := self.short_term.last_command)):
                repeated = last
                again = await self._understand(last)
                await self.bus.publish(NovaEvent(type=EventType.AGENT_WORKING, task_id=task_id, agent=MEMORY,
                                                 message=f"Pichla kaam dobara: \"{last[:80]}\""))
                requested += [i for i in (await self._route(again)).intents if i.name != "repeat_last"]
                continue
            requested.append(intent)
        intents: list[Intent] = []
        for intent in requested:  # after repeats, so "dobara karo" after "work start karo" runs the workflow too
            if intent.name == "run_workflow" and self.memory is not None:
                found = self.memory.workflow(str(intent.entities.get("workflow") or ""))
                if found is not None:
                    row, steps = found
                    workflow = row["name"]
                    self.db.mark_workflow_run(row["id"])
                    self.db.add_activity(task_id=task_id, task_name="command:run_workflow", agent=MEMORY,
                                         action="run_workflow", execution_status="expanded",
                                         final_result=f"{row['name']}: {len(steps)} cheezein")
                    await self.bus.publish(NovaEvent(type=EventType.AGENT_WORKING, task_id=task_id, agent=MEMORY,
                                                     message=f"'{row['name']}' workflow: "
                                                             + ", ".join(s.label for s in steps)))
                    intents += [s.intent(intent.language) for s in steps]
                    continue
            intents.append(intent)
        if not intents:  # e.g. the repeated command was itself only "dobara karo"
            intents = [i for i in understanding.intents]
        return understanding.model_copy(update={"intents": intents}), workflow, repeated

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
        elif intent.name in BROWSER_INTENTS and step.status == "ready" and self.browser is not None:
            outcome = await self._run_browser(task_id, step)
        elif intent.name in RESEARCH_INTENTS and step.status == "ready" and self.research is not None:
            outcome = await self._run_research(task_id, step)
        elif intent.name in FILE_INTENTS and step.status == "ready" and self.files is not None and step.prepared:
            outcome = await self._run_file(task_id, step)
        elif intent.name in CODING_INTENTS and step.status == "ready" and self.coding is not None and step.prepared:
            outcome = await self._run_coding(task_id, step)
        elif intent.name in self.prepared_agents and step.status == "ready" and step.prepared:
            outcome = await self._run_prepared_agent(task_id, step)
        elif step.status == "skipped" and step.result:
            # The agent answered without acting: "kaun si file?", "nahi mila", "pehle errors check karo".
            outcome = AgentOutcome(step.result, step.agent, step.action, executed=False)
        elif step.status == "denied" and step.permission == "refused":
            # NOVA itself refuses (e.g. a password field) - the user was not even asked.
            outcome = AgentOutcome(step.result or "Ye kaam NOVA nahi karta.", step.agent, step.action, executed=False)
        elif step.status == "denied":
            reply = ("Aap ka jawab nahi aaya, is liye ye kaam nahi kiya" if step.permission == "timeout"
                     else "Theek hai, ijazat nahi mili, is liye ye kaam nahi kiya")
            outcome = AgentOutcome(f"{reply}: {step.description}.", step.agent, step.action, executed=False)
        elif step.status == "needs_permission":
            # No Permission Engine available: risky steps are never executed.
            outcome = AgentOutcome(build_permission_response(intent, step.description), step.agent, step.action,
                                   executed=False)
        else:
            named = intent.name in ("greeting", "thanks")
            user_name = self.memory.user_name() if self.memory is not None and named else None
            outcome = AgentOutcome(build_response(intent, self.assistant_name, plan.answer, user_name), step.agent,
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
            "denied": "not_executed_denied",
        }.get(step.status, step.status)
        permission_status = {
            "approved": "approved_by_user", "rule": "approved_by_saved_rule", "denied": "denied", "timeout": "timeout",
            "refused": "refused_by_nova", "remote": "approved_by_remote_user",
        }.get(step.permission or "", "required_pending" if step.status == "needs_permission" else "not_required")
        self.db.add_activity(
            task_id=task_id,
            task_name=f"command:{intent.name}",
            agent=outcome.agent,
            action=outcome.action,
            permission_status=permission_status,
            execution_status=execution,
            test_status=outcome.test_status,
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

    async def _route(self, understanding: Understanding) -> Understanding:
        """Send each intent to the agent that can actually do it, using what is on screen right now:
        - "YouTube kholo" with no YouTube app installed -> open the website;
        - click/type while the user's window is NOVA's own browser -> act inside the web page."""
        routed: list[Intent] = []
        browser_is_target: bool | None = None
        for intent in understanding.intents:
            e = intent.entities
            if intent.name == "open_app" and (app := str(e.get("app") or "")):
                if self.memory is not None and self.memory.workflow(app):  # "study start karo": the saved workflow
                    intent = intent.model_copy(update={"name": "run_workflow", "entities": {"workflow": app}})
                elif self.browser is not None:
                    profile = self.discovery.profile
                    installed = profile is not None and find_app(profile.apps, app) is not None
                    if not installed and site_for(app):
                        intent = intent.model_copy(update={"name": "open_website", "entities": {"url": app}})
            if intent.name in ("mouse_click", "type_text") and self.browser is not None and self.computer is not None:
                if browser_is_target is None:
                    browser_is_target = await asyncio.to_thread(self._browser_is_target)
                if browser_is_target:
                    if intent.name == "mouse_click":
                        intent = intent.model_copy(update={"name": "browser_click"})
                    else:
                        intent = intent.model_copy(update={"name": "browser_type",
                                                           "entities": {"text": e.get("text", "")}})
            routed.append(intent)
        return understanding.model_copy(update={"intents": routed})

    def _browser_is_target(self) -> bool:
        assert self.computer is not None and self.browser is not None
        window = self.computer._last_user_window()
        pid = self.browser.browser.pid()
        return bool(window and pid and window.pid == pid)

    async def _target_for(self, step: PlanStep) -> TargetContext | str:
        """Where a risky step would act, or a refusal reason if NOVA will not do it at all."""
        intent = step.intent
        if isinstance(step.prepared, Prepared):
            return self._prepared_target(step.prepared)
        if intent.name in BROWSER_INTENTS and self.browser is not None:
            target = await asyncio.to_thread(self.browser.describe_target, intent)
            if target.refusal:
                return target.refusal
            element = target.element.text if target.element and target.element.found else None
            step.element_text = element
            return TargetContext(title=target.title, process=f"browser:{target.host}", element=element,
                                 executable=intent.name == "download" and download_is_executable(
                                     str(intent.entities.get("target") or ""), target.element))
        if self.computer is not None:
            title, process = await asyncio.to_thread(self.computer.describe_target, intent)
            return TargetContext(title=title, process=process)
        return TargetContext()

    async def _seek_permission(self, task_id: str, plan: Plan, source: str) -> None:
        """Ask the user (or apply a remembered approval) for every step that needs permission."""
        risky = [s for s in plan.steps if s.status == "needs_permission"]
        if not risky or self.permissions is None:
            return
        items = []
        for step in list(risky):
            target = await self._target_for(step)
            if isinstance(target, str):
                step.status, step.permission, step.result = "denied", "refused", target
                risky.remove(step)
                continue
            item = self.permissions.make_item(step.id, step.intent.name, step.intent.entities, step.description,
                                              step.risk, target)
            step.risk, step.reasons = item.risk, item.reasons
            items.append(item)
        if not items:
            return
        await self.set_state(NovaState.WAITING_FOR_PERMISSION, task_id)
        decisions = await self.permissions.request(task_id, items, source)
        for step in risky:
            decision = decisions[step.id]
            if decision.approved:
                step.status = "ready"
                step.permission = "rule" if decision.decided_by == "rule" else "approved"
            else:
                step.status = "denied"
                step.permission = "timeout" if decision.decided_by == "timeout" else "denied"

    async def _run_browser(self, task_id: str, step: PlanStep) -> AgentOutcome:
        assert self.browser is not None
        await self.set_state(NovaState.WORKING, task_id)
        await self.bus.publish(NovaEvent(type=EventType.AGENT_STARTED, task_id=task_id, agent=step.agent,
                                         message=f"{step.description}..."))
        approved = is_approved(step)
        if step.intent.name == "read_page":
            page = await asyncio.to_thread(self.browser.page_text)
            if isinstance(page, ControlOutcome):
                result = page
            else:
                await self.bus.publish(NovaEvent(type=EventType.AGENT_WORKING, task_id=task_id, agent=step.agent,
                                                 message="Page ka khulasa bana raha hai..."))
                summary = await self.research.summarise_page(page[0], page[2]) if self.research else None
                result = self.browser.page_outcome(*page, summary=summary)
        else:
            element = ElementInfo(True, step.element_text) if step.element_text else None
            result = await asyncio.to_thread(self.browser.run, step.intent, approved, element)
        return await self._report(task_id, step, result)

    async def _run_research(self, task_id: str, step: PlanStep) -> AgentOutcome:
        assert self.research is not None
        await self.set_state(NovaState.WORKING, task_id)

        async def progress(message: str) -> None:
            await self.bus.publish(NovaEvent(type=EventType.AGENT_WORKING, task_id=task_id, agent=step.agent,
                                             message=message))

        query = str(step.intent.entities.get("query") or "").strip()
        if not query:
            return AgentOutcome("Kis cheez ke baare mein dhoondna hai?", step.agent, step.action, False)
        await self.bus.publish(NovaEvent(type=EventType.AGENT_STARTED, task_id=task_id, agent=step.agent,
                                         message=f"{step.description}: {query}"))
        try:
            if step.intent.name == "research":
                found = await self.research.report(query, progress)
            else:
                found = await self.research.answer(query, progress)
        except SearchError as exc:
            return AgentOutcome(f"Web se maloomat nahi mil saki: {exc}.", step.agent, step.action, False)
        if found.report_path is not None:
            ok = found.report_path.exists() and found.report_path.stat().st_size > 0
            result = ControlOutcome(found.response, step.action, True, "passed" if ok else "failed",
                                    str(found.report_path))
        else:
            result = ControlOutcome(found.response, step.action, bool(found.sources), "not_applicable")
        return await self._report(task_id, step, result)

    @staticmethod
    def _prepared_target(p: Prepared) -> TargetContext:
        return TargetContext(title=p.summary, scope_key=p.scope_key, preview=p.preview, count=p.count, size=p.size,
                             executes_code=p.executes_code, network=p.network, always_ask=p.always_ask,
                             min_risk=p.min_risk, agent_reasons=tuple(p.reasons))

    async def _prepare_steps(self, task_id: str, plan: Plan) -> None:
        """File/Coding steps: resolve exactly what will happen before anyone is asked. A step that turns out
        to run project code (or to be a big delete) is raised to "needs permission" here."""
        for step in plan.steps:
            name = step.intent.name
            if step.status not in ("ready", "needs_permission"):
                continue
            if name in FILE_INTENTS and self.files is not None:
                result: Prepared | Reply = await asyncio.to_thread(self.files.prepare, step.intent)
            elif (name in CODING_INTENTS and self.coding is not None) or name in self.prepared_agents:
                async def progress(message: str, agent: str = step.agent) -> None:
                    await self.bus.publish(NovaEvent(type=EventType.AGENT_WORKING, task_id=task_id, agent=agent,
                                                     message=message))

                agent = self.coding if name in CODING_INTENTS else self.prepared_agents[name]
                result = await agent.prepare(step.intent, progress)
            else:
                continue
            if isinstance(result, Reply):
                step.result = result.message
                step.status, step.permission = ("denied", "refused") if result.refused else ("skipped", None)
                continue
            step.prepared = result
            if step.status == "ready" and self.permissions is not None:
                risk, reasons = classify(name, step.intent.entities, step.risk, self._prepared_target(result))
                if risk != "low":
                    step.status, step.risk, step.reasons = "needs_permission", risk, reasons

    async def _run_file(self, task_id: str, step: PlanStep) -> AgentOutcome:
        assert self.files is not None
        await self.set_state(NovaState.WORKING, task_id)
        await self.bus.publish(NovaEvent(type=EventType.AGENT_STARTED, task_id=task_id, agent=step.agent,
                                         message=f"{step.description}: {step.prepared.summary}"))
        approved = is_approved(step)
        try:
            result, content = await asyncio.to_thread(self.files.run, step.intent, step.prepared, approved)
        except (ScopeError, OSError) as exc:  # e.g. the file was moved or locked after the plan was made
            message = str(exc) if isinstance(exc, ScopeError) else f"Windows ne ye kaam nahi karne diya: {exc}"
            result, content = ControlOutcome(message, step.action, False, "failed"), None
        if content is not None and step.intent.entities.get("summary") and self.research is not None:
            await self.bus.publish(NovaEvent(type=EventType.AGENT_WORKING, task_id=task_id, agent=step.agent,
                                             message="File ka khulasa bana raha hai..."))
            summary = await self.research.summarise_page(Path(result.detail or "").name, content.text)
            if summary:
                result.response = f"\"{Path(result.detail or '').name}\" ({content.detail}) ka khulasa:\n{summary}"
        return await self._report(task_id, step, result)

    async def _run_coding(self, task_id: str, step: PlanStep) -> AgentOutcome:
        assert self.coding is not None
        await self.set_state(NovaState.WORKING, task_id)
        await self.bus.publish(NovaEvent(type=EventType.AGENT_STARTED, task_id=task_id, agent=step.agent,
                                         message=f"{step.description}: {step.prepared.summary}"))

        async def progress(message: str) -> None:
            await self.bus.publish(NovaEvent(type=EventType.AGENT_WORKING, task_id=task_id, agent=step.agent,
                                             message=message))

        approved = is_approved(step)
        try:
            result = await self.coding.run(step.intent, step.prepared, approved, progress)
        except (ScopeError, OSError) as exc:
            message = str(exc) if isinstance(exc, ScopeError) else f"Command nahi chal saki: {exc}"
            result = ControlOutcome(message, step.action, False, "failed")
        return await self._report(task_id, step, result)

    async def _run_prepared_agent(self, task_id: str, step: PlanStep) -> AgentOutcome:
        """System settings, Communication and Design agents: run exactly what was prepared (and approved)."""
        agent = self.prepared_agents[step.intent.name]
        await self.set_state(NovaState.WORKING, task_id)
        await self.bus.publish(NovaEvent(type=EventType.AGENT_STARTED, task_id=task_id, agent=step.agent,
                                         message=f"{step.description}: {step.prepared.summary}"))

        async def progress(message: str) -> None:
            await self.bus.publish(NovaEvent(type=EventType.AGENT_WORKING, task_id=task_id, agent=step.agent,
                                             message=message))

        approved = is_approved(step)
        try:
            result = await agent.run(step.intent, step.prepared, approved, progress)
        except (ScopeError, OSError) as exc:
            message = str(exc) if isinstance(exc, ScopeError) else f"Windows ne ye kaam nahi karne diya: {exc}"
            result = ControlOutcome(message, step.action, False, "failed")
        return await self._report(task_id, step, result)

    async def _report(self, task_id: str, step: PlanStep, result: ControlOutcome) -> AgentOutcome:
        """Publish what an agent did and how it was verified; return it for the step log."""
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
                            verification=result.verification, test_status=result.test_status or "not_run")

    async def _run_computer(self, task_id: str, step: PlanStep) -> AgentOutcome:
        """Run a computer-control action and report its verification (spec: never assume success)."""
        assert self.computer is not None
        if step.intent.name in ("open_app", "focus_app", "window_control", "close_app"):
            await self._ensure_profile(task_id)  # app names are resolved through the discovered catalog
        await self.set_state(NovaState.WORKING, task_id)
        await self.bus.publish(NovaEvent(type=EventType.AGENT_STARTED, task_id=task_id, agent=step.agent,
                                         message=f"{step.description}..."))
        approved = is_approved(step)
        result = await asyncio.to_thread(self.computer.run, step.intent, approved)
        return await self._report(task_id, step, result)

    def _compose(self, plan: Plan, outcomes: list[AgentOutcome]) -> str:
        if plan.workflow:
            pairs = list(zip(plan.steps, outcomes))
            saved = [o.response for s, o in pairs if s.intent.name == "save_workflow"]
            opened = [o.response for s, o in pairs if s.intent.name != "save_workflow"]
            lines = saved or [f"'{plan.workflow}' workflow ({len(opened)} cheezein):"]
            return "\n".join(lines + [f"{n}. {r}" for n, r in enumerate(opened, start=1)])
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

    # ------------------------------------------------------------------ Multi-PC: a paired PC asks this PC

    async def plan_remote(self, text: str, origin: str, origin_id: str) -> dict[str, Any]:
        """Work out (here, with this PC's own brain and apps) what a paired PC's command would do - nothing runs yet.
        Each step is allowed, needs the sender's permission ("ask"), only answers ("reply"), or is refused."""
        now = time.monotonic()
        self._remote_plans = {k: v for k, v in self._remote_plans.items() if now - v[4] < REMOTE_PLAN_TTL_S}
        task_id = uuid.uuid4().hex[:12]
        await self.bus.publish(NovaEvent(type=EventType.REMOTE_TASK, task_id=task_id, agent="Multi-PC Agent",
                                         message=f"{origin} ne kaha: \"{text[:120]}\" — plan bana raha hai",
                                         data={"from": origin, "stage": "plan"}))
        understanding = await self.providers.understand(text)  # no conversation context of this PC's user
        understanding = await self._route(understanding)
        understanding, workflow, _ = await self._expand(task_id, understanding, repeats=False)
        plan = build_plan(understanding)
        plan.workflow = workflow
        for step in plan.steps:  # refused before any agent prepares it (no questions, nothing touched on this PC)
            if step.intent.name not in REMOTE_ALLOWED:
                step.status, step.permission, step.result = "denied", "refused", REMOTE_REFUSED
        await self._prepare_steps(task_id, plan)
        steps = []
        for step in plan.steps:
            if step.status in ("skipped", "denied"):  # the agent answered ("kaun si file?") or refused by itself
                steps.append({"id": step.id, "description": step.description, "status": "reply" if step.status ==
                              "skipped" else "refused", "result": step.result, "risk": step.risk})
                continue
            why = ("Ye kaam abhi mumkin nahi" if step.status == "unavailable"
                   else remote_verdict(step.intent.name, step.risk))
            if why:
                step.status, step.permission, step.result = "denied", "refused", why
            elif step.status == "needs_permission" and self.permissions is not None:
                target = await self._target_for(step)
                if isinstance(target, str):
                    step.status, step.permission, step.result = "denied", "refused", target
                else:
                    item = self.permissions.make_item(step.id, step.intent.name, step.intent.entities,
                                                      step.description, step.risk, target)
                    step.risk, step.reasons, step.description = item.risk, item.reasons, item.description
                    if (why := remote_verdict(step.intent.name, step.risk)) is not None:
                        step.status, step.permission, step.result = "denied", "refused", why
            elif step.status == "needs_permission":
                step.status, step.permission, step.result = "denied", "refused", "Ijazat ka nizam nahi"
            status = {"needs_permission": "ask", "denied": "refused"}.get(step.status, "ready")
            steps.append({"id": step.id, "description": step.description, "status": status, "risk": step.risk,
                          "reasons": step.reasons[:3], "result": step.result if status == "refused" else None})
        for step in plan.steps:  # this PC's own record of what another PC was refused
            if step.status == "denied":
                self.db.add_activity(task_id=task_id, task_name=f"command:{step.intent.name}", agent="Multi-PC Agent",
                                     action="remote_refused", permission_status="refused_by_nova",
                                     execution_status="not_executed_denied", final_result=f"{origin}: {step.result}")
        if all(s["status"] == "refused" for s in steps):
            await self.bus.publish(NovaEvent(type=EventType.REMOTE_TASK, task_id=task_id, agent="Multi-PC Agent",
                                             message=f"{origin} ka kaam mana kiya: {steps[0]['result']}",
                                             data={"from": origin, "stage": "refused"}))
        else:
            self._remote_plans[plan.id] = (plan, origin_id, task_id, text, now)
        return {"plan_id": plan.id, "steps": steps}

    async def run_remote(self, plan_id: str, approved: bool, origin: str, origin_id: str) -> dict[str, Any]:
        """Run exactly the plan made for that PC. `approved`: its user said yes to the steps that needed permission."""
        entry = self._remote_plans.get(plan_id)
        if entry is None or entry[1] != origin_id or time.monotonic() - entry[4] > REMOTE_PLAN_TTL_S:
            return {"response": "Ye plan purana ho gaya — command dobara dein.", "executed": False,
                    "verification": "not_applicable"}
        del self._remote_plans[plan_id]  # a plan runs once
        plan, _, task_id, text, _ = entry
        for step in plan.steps:
            if step.status == "needs_permission":
                step.status, step.permission = ("ready", "remote") if approved else ("denied", "denied")
        await self.bus.publish(NovaEvent(type=EventType.REMOTE_TASK, task_id=task_id, agent="Multi-PC Agent",
                                         message=f"{origin} ka kaam shuru: \"{text[:120]}\"",
                                         data={"from": origin, "stage": "run"}))
        outcomes = []
        for step in plan.steps:
            outcome = await self._run_step(task_id, step, plan)
            if self._may_retry(step, outcome):
                outcome = await self._retry_step(task_id, step, plan, ask=False)
            outcomes.append(outcome)
        response = self._compose(plan, outcomes)
        verifications = {o.verification for o in outcomes if o.executed}
        verification = ("failed" if "failed" in verifications else "passed" if "passed" in verifications
                        else "unverified" if "unverified" in verifications else "not_applicable")
        self.db.add_conversation(task_id=task_id, source="remote", user_text=f"[{origin}] {text}",
                                 detected_language=plan.steps[0].intent.language,
                                 intent=",".join(s.intent.name for s in plan.steps), response=response,
                                 status="understood")
        await self.bus.publish(NovaEvent(type=EventType.REMOTE_TASK, task_id=task_id, agent="Multi-PC Agent",
                                         message=f"{origin} ka kaam mukammal: {response[:160]}",
                                         data={"from": origin, "stage": "done", "response": response}))
        await self.bus.publish(NovaEvent(type=EventType.TASK_COMPLETED, task_id=task_id, agent=ORCHESTRATOR,
                                         message="Task mukammal"))
        await self.set_state(NovaState.COMPLETED, task_id)
        await self.set_state(self.rest_state)
        return {"response": response, "executed": any(o.executed for o in outcomes), "verification": verification}

    def _may_retry(self, step: PlanStep, outcome: AgentOutcome) -> bool:
        """Error handling (spec 32): only a safe, low-risk action that nobody had to approve is retried by itself."""
        return (outcome.verification == "failed" and step.intent.name in SAFE_RETRY and step.risk == "low"
                and step.permission is None)

    async def _retry_step(self, task_id: str, step: PlanStep, plan: Plan, ask: bool = True) -> AgentOutcome:
        await self.bus.publish(NovaEvent(type=EventType.RETRY, task_id=task_id, agent=ORCHESTRATOR,
                                         message=f"Verify nahi hua — ek dafa dobara koshish: {step.description}"))
        step.status, step.result = "ready", None
        second = await self._run_step(task_id, step, plan)
        if second.verification != "failed":
            second.response += " (Pehli koshish verify nahi hui thi; dobara karne par ho gaya.)"
            return second
        step.status = "failed"
        if ask and self.short_term.pending is None:  # explain and ask - never a third try on its own
            question = "Dobara koshish bhi kaam nahi aayi. Kya main ek dafa aur koshish karoon? (haan/nahi)"
            self.short_term.ask("retry", question, {"intents": [step.intent.model_dump()]}, ttl_s=180)
            second.response += f"\n{question}"
        return second

    async def _fail(self, task_id: str, text: str, source: str, exc: Exception) -> CommandResult:
        if self.on_crash is not None:
            try:
                await self.on_crash(exc, task_id)
            except Exception:  # logging a bug must never hide the original failure
                log.exception("Could not log the crash as a bug")
        response = build_error_response()
        self.short_term.add_turn(text, response, command=False, outcome="failed")
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
