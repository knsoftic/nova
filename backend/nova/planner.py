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
    # Browser Agent: NOVA's own browser window. Reading/moving is low risk; acting on a page needs permission.
    "web_search": Capability("Browser Agent", "web_search", "low", None, "Web par search kholna"),
    "open_website": Capability("Browser Agent", "open_website", "low", None, "Website kholna"),
    "read_page": Capability("Browser Agent", "read_page", "low", None, "Web page parhna"),
    "browser_nav": Capability("Browser Agent", "browser_nav", "low", None, "Browser mein scroll/back/forward"),
    "browser_click": Capability("Browser Agent", "browser_click", "medium", None, "Web page par click karna"),
    "browser_type": Capability("Browser Agent", "browser_type", "medium", None, "Web page par likhna"),
    "download": Capability("Browser Agent", "download", "medium", None, "File download karna"),
    # Research Agent: reads public web sources through official search APIs; saves reports in Documents\NOVA.
    "research": Capability("Research Agent", "research_report", "low", None, "Research report banana"),
    "web_answer": Capability("Research Agent", "web_answer", "low", None, "Web se taza jawab dhoondna"),
    # File Agent (inside the allowed folders only). Creating/reading/copying loses nothing; changing or
    # removing existing files needs permission. Delete always goes to the Recycle Bin.
    "search_files": Capability("File Agent", "search_files", "low", None, "Files dhoondna"),
    "create_folder": Capability("File Agent", "create_folder", "low", None, "Folder banana"),
    "create_file": Capability("File Agent", "create_file", "low", None, "File banana"),
    "open_file": Capability("File Agent", "open_file", "low", None, "File/folder kholna"),
    "read_file": Capability("File Agent", "read_file", "low", None, "File parhna"),
    "copy_file": Capability("File Agent", "copy_file", "low", None, "File copy karna"),
    "folder_report": Capability("File Agent", "folder_report", "low", None, "Folder ki report banana"),
    "rename_file": Capability("File Agent", "rename_file", "medium", None, "File ka naam badalna"),
    "move_file": Capability("File Agent", "move_file", "medium", None, "File move karna"),
    "delete_file": Capability("File Agent", "delete_file", "medium", None, "File Recycle Bin mein bhejna"),
    "edit_file": Capability("File Agent", "edit_file", "medium", None, "File mein likhna/badalna"),
    "organize_folder": Capability("File Agent", "organize_folder", "medium", None, "Folder organize karna"),
    "undo_file_op": Capability("File Agent", "undo_file_op", "medium", None, "Pichla file kaam wapas karna"),
    # Coding Agent. Checks/commands that run the project's own code are raised to medium by the Permission
    # Engine when prepared (built-in syntax checks and git status stay low).
    "open_project": Capability("Coding Agent", "open_project", "low", None, "Project VS Code mein kholna"),
    "inspect_project": Capability("Coding Agent", "inspect_project", "low", None, "Project ka jaiza lena"),
    "check_errors": Capability("Coding Agent", "check_errors", "low", None, "Project mein errors check karna"),
    "run_command": Capability("Coding Agent", "run_command", "low", None, "Project command chalana"),
    "run_tests": Capability("Coding Agent", "run_tests", "medium", None, "Project ke tests chalana"),
    "explain_error": Capability("Coding Agent", "explain_error", "low", None, "Error samjhana"),
    "fix_error": Capability("Coding Agent", "fix_error", "medium", None, "Error theek karna (code badalna)"),
    "modify_code": Capability("Coding Agent", "modify_code", "medium", None, "Code badalna"),
    # Windows settings (System Agent). Volume/brightness/mute are low; the agent raises dark mode and turning
    # Wi-Fi/Bluetooth off to medium when it prepares them. Security settings are refused.
    "change_setting": Capability("System Agent", "change_setting", "low", None, "Setting badalna"),
    "open_settings": Capability("System Agent", "open_settings", "low", None, "Settings page kholna"),
    # Communication Agent: every send is asked (raised to medium, never remembered); drafts are low.
    "send_message": Capability("Communication Agent", "send_message", "low", None, "Message/email"),
    "save_contact": Capability("Communication Agent", "save_contact", "low", None, "Contact save karna"),
    "list_contacts": Capability("Communication Agent", "list_contacts", "low", None, "Contacts dikhana"),
    "delete_contact": Capability("Communication Agent", "delete_contact", "low", None, "Contact hatana"),
    # Design Agent: new files only (originals untouched).
    "edit_image": Capability("Design Agent", "edit_image", "low", None, "Tasveer badalna (nayi file)"),
    "create_design": Capability("Design Agent", "create_design", "low", None, "Design banana"),
    "open_with": Capability("Design Agent", "open_with", "low", None, "File app mein kholna"),
    # Memory Agent (Phase 9). Saving what the user asked is low; forgetting/deleting is permanent, so it is never
    # below medium here, and the agent raises "everything" to high. Workflows only open things.
    "remember_fact": Capability("Memory Agent", "remember_fact", "low", None, "Baat yaad rakhna"),
    "recall_memory": Capability("Memory Agent", "recall_memory", "low", None, "Yaadein dekhna"),
    "forget_memory": Capability("Memory Agent", "forget_memory", "medium", None, "Yaad mitana"),
    "search_history": Capability("Memory Agent", "search_history", "low", None, "History mein dhoondna"),
    "clear_history": Capability("Memory Agent", "clear_history", "medium", None, "History mitana"),
    "save_workflow": Capability("Memory Agent", "save_workflow", "low", None, "Workflow save karna"),
    "list_workflows": Capability("Memory Agent", "list_workflows", "low", None, "Workflows dikhana"),
    "delete_workflow": Capability("Memory Agent", "delete_workflow", "medium", None, "Workflow mitana"),
    "run_workflow": Capability("Memory Agent", "run_workflow", "low", None, "Workflow chalana"),
    "repeat_last": Capability("Memory Agent", "repeat_last", "low", None, "Pichla kaam dobara"),
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
    # For web-page clicks: the exact element text the user approved (re-checked before clicking).
    element_text: str | None = None
    # File/Coding steps: what exactly will happen, worked out before asking (agents.prepared.Prepared).
    prepared: Any = Field(default=None, exclude=True)


class Plan(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:10])
    steps: list[PlanStep]
    provider: str
    fallback_reason: str | None = None
    answer: str | None = None
    workflow: str | None = None  # the steps come from this saved workflow

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
    if intent.name == "forget_memory" and intent.entities.get("scope") == "conversation":
        return "low"  # "naya topic": only the current conversation context is dropped, nothing saved is deleted
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
