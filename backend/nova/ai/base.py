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
    "unknown",
)

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

    async def understand(self, text: str, context: list[ConversationTurn] | None = None) -> Understanding:
        intent = await self.detect_intent(text)
        return Understanding(intents=[intent], provider=self.name)

    async def is_available(self) -> bool:
        return True

    def configure_wake(self, assistant_name: str, wake_word: str) -> None:
        """Tell the provider which name/wake word prefixes to ignore. Optional."""
