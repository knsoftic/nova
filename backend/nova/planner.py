"""Task planner: turns understood intents into an ordered plan of agent steps.

Risk levels and availability come only from CAPABILITIES below, never from AI output, so a
model can at most choose *which known capability* to plan - not how risky it is.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from .ai.base import Intent, Understanding

Risk = Literal["low", "medium", "high"]
StepStatus = Literal["ready", "unavailable", "needs_permission", "denied", "done", "failed", "skipped"]

PERMISSION_ENGINE_PHASE = 7


@dataclass(frozen=True)
class Capability:
    agent: str
    action: str
    risk: Risk
    available_from_phase: int | None  # None = available now
    description: str  # Roman Urdu, shown in the plan


CAPABILITIES: dict[str, Capability] = {
    "greeting": Capability("Orchestrator", "respond", "low", None, "Salam ka jawab"),
    "help": Capability("Orchestrator", "respond", "low", None, "Madad ki maloomat"),
    "chat": Capability("Orchestrator", "answer_question", "low", None, "Sawal ka jawab"),
    "unknown": Capability("Orchestrator", "respond", "low", None, "Wazahat maangna"),
    "system_info": Capability("System Agent", "read_system_info", "low", None, "System maloomat parhna"),
    "app_check": Capability("System Agent", "app_lookup", "low", None, "Application dhoondna"),
    "rescan_system": Capability("System Agent", "rescan", "low", None, "System dobara scan karna"),
    "open_app": Capability("System Agent", "launch_app", "low", None, "Application kholna"),
    "focus_app": Capability("System Agent", "focus_window", "low", None, "Window saamne lana"),
    "window_control": Capability("System Agent", "window_control", "low", None, "Window chhoti/bari karna"),
    "read_screen": Capability("System Agent", "read_screen", "low", None, "Screen parhna"),
    "screenshot": Capability("System Agent", "screenshot", "low", None, "Screenshot lena"),
    # Changes things inside other apps (unsaved work, typed text): needs the user's permission.
    "close_app": Capability("System Agent", "close_app", "medium", None, "Application band karna"),
    "keyboard_shortcut": Capability("System Agent", "keyboard_shortcut", "medium", None, "Keyboard shortcut dabana"),
    "type_text": Capability("System Agent", "type_text", "medium", None, "Text type karna"),
    "mouse_click": Capability("System Agent", "mouse_click", "medium", None, "Mouse se click karna"),
    "web_search": Capability("Browser Agent", "web_search", "low", 8, "Web par search karna"),
    "create_folder": Capability("File Agent", "create_folder", "medium", 8, "Folder banana"),
    "change_setting": Capability("System Agent", "change_setting", "medium", 8, "Setting badalna"),
    "run_workflow": Capability("Orchestrator", "run_workflow", "low", 9, "Workflow chalana"),
}


class PlanStep(BaseModel):
    id: int
    intent: Intent
    agent: str
    action: str
    risk: Risk
    description: str
    status: StepStatus
    available_from_phase: int | None = None
    result: str | None = None
    # Set by the Permission Engine: approved | rule (remembered approval) | denied | timeout
    permission: str | None = None
    reasons: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    steps: list[PlanStep]
    provider: str
    fallback_reason: str | None = None
    answer: str | None = None

    @property
    def is_compound(self) -> bool:
        return len(self.steps) > 1

    def summary(self) -> list[dict[str, Any]]:
        return [
            {"id": s.id, "agent": s.agent, "action": s.action, "risk": s.risk, "status": s.status,
             "description": s.description, "intent": s.intent.name,
             "available_from_phase": s.available_from_phase, "permission": s.permission}
            for s in self.steps
        ]


# Shortcuts that only read or select (nothing is changed or lost) are low risk.
LOW_RISK_SHORTCUTS = {"copy", "select_all", "find", "escape"}


def risk_for(intent: Intent, cap: Capability) -> Risk:
    if intent.name == "keyboard_shortcut" and intent.entities.get("keys") in LOW_RISK_SHORTCUTS:
        return "low"
    return cap.risk


def build_plan(understanding: Understanding) -> Plan:
    intents = understanding.intents
    # A greeting/unknown next to real requests adds nothing to the plan.
    meaningful = [i for i in intents if i.name not in ("greeting", "unknown")]
    if meaningful and len(meaningful) < len(intents):
        intents = meaningful

    steps: list[PlanStep] = []
    for n, intent in enumerate(intents, start=1):
        cap = CAPABILITIES.get(intent.name, CAPABILITIES["unknown"])
        risk = risk_for(intent, cap)
        if cap.available_from_phase is not None:
            status: StepStatus = "unavailable"
        elif risk != "low":
            # No medium/high-risk action may run before the Permission Engine exists.
            status = "needs_permission"
        else:
            status = "ready"
        steps.append(
            PlanStep(
                id=n,
                intent=intent,
                agent=cap.agent,
                action=cap.action,
                risk=risk,
                description=cap.description,
                status=status,
                available_from_phase=cap.available_from_phase,
            )
        )
    return Plan(steps=steps, provider=understanding.provider, fallback_reason=understanding.fallback_reason,
                answer=understanding.answer)
