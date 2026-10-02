"""AI provider contract. Any provider (rule-based, Ollama, cloud) must implement this interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

# Every intent the orchestrator knows how to plan. Providers must never return anything else.
KNOWN_INTENTS = (
    "greeting",
    "help",
    "chat",  # general question / small talk, answered in words only
    "open_app",
    "app_check",
    "web_search",
    "create_folder",
    "system_info",
    "rescan_system",
    "change_setting",
    "run_workflow",
    # computer control (Phase 6)
    "close_app",
    "focus_app",
    "window_control",
    "read_screen",
    "screenshot",
    "keyboard_shortcut",
    "type_text",
    "mouse_click",
    # browser + research (Phase 8A)
    "open_website",
    "read_page",
    "browser_nav",
    "browser_click",
    "browser_type",
    "download",
    "research",
    "web_answer",
    # files + coding (Phase 8B)
    "search_files",
    "create_file",
    "open_file",
    "read_file",
    "rename_file",
    "move_file",
    "copy_file",
    "delete_file",
    "edit_file",
    "organize_folder",
    "folder_report",
    "undo_file_op",
    "open_project",
    "inspect_project",
    "run_tests",
    "check_errors",
    "run_command",
    "explain_error",
    "fix_error",
    "modify_code",
    # system settings, messages, design (Phase 8C)
    "open_settings",
    "send_message",
    "save_contact",
    "list_contacts",
    "delete_contact",
    "edit_image",
    "create_design",
    "open_with",
    # memory, history, workflows (Phase 9)
    "remember_fact",
    "recall_memory",
    "forget_memory",
    "search_history",
    "clear_history",
    "save_workflow",
    "list_workflows",
    "delete_workflow",
    "repeat_last",
    "unknown",
)

BROWSER_NAV_ACTIONS = ("scroll_down", "scroll_up", "back", "forward", "reload")
EDIT_ACTIONS = ("append", "replace")
SETTING_NAMES = ("volume", "mute", "unmute", "brightness", "theme", "wifi", "bluetooth", "default_browser", "other")
CHANNELS = ("whatsapp", "email")
IMAGE_OPERATIONS = ("resize", "fit", "convert", "compress", "rotate", "flip", "grayscale", "caption", "watermark")
HISTORY_PERIODS = ("today", "yesterday", "week", "month")
WORKFLOW_ACTIONS = ("replace", "add", "remove")
REPEAT_WHAT = ("command", "response")

WINDOW_ACTIONS = ("minimize", "maximize", "restore", "show_desktop")
SHORTCUT_NAMES = ("copy", "paste", "cut", "undo", "redo", "select_all", "save", "new_tab", "close_tab", "find",
                  "refresh", "enter", "escape")

SYSTEM_TOPICS = (
    "summary", "cpu", "ram", "gpu", "storage", "windows", "devices", "displays",
    "network", "admin", "browsers", "apps", "running",
)


class Intent(BaseModel):
    name: str  # one of KNOWN_INTENTS
    confidence: float = 0.0
    language: str = "unknown"
    entities: dict[str, Any] = Field(default_factory=dict)
    provider: str = ""


class ConversationTurn(BaseModel):
    user: str
    assistant: str


class Understanding(BaseModel):
    """What the brain made of one utterance: one or more intents (compound commands)."""

    intents: list[Intent]
    provider: str
    latency_ms: int = 0
    answer: str | None = None  # model-written reply for "chat" intents
    fallback_reason: str | None = None  # set when the preferred provider failed and rules were used


class AIProvider(ABC):
    name: str = "base"
    is_local: bool = True

    @abstractmethod
    async def detect_intent(self, text: str) -> Intent:
        """Map a user utterance (any supported language) to a single structured intent."""

    async def understand(self, text: str, context: list[ConversationTurn] | None = None,
                         memories: list[str] | None = None) -> Understanding:
        """`context`: the last turns (short-term memory). `memories`: related things the user asked NOVA to remember."""
        intent = await self.detect_intent(text)
        return Understanding(intents=[intent], provider=self.name)

    async def is_available(self) -> bool:
        return True

    def configure_wake(self, assistant_name: str, wake_word: str) -> None:
        """Tell the provider which name/wake word prefixes to ignore. Optional."""
