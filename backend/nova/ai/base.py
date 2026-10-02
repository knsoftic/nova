"""AI provider contract. Any provider (rule-based, Ollama, cloud) must implement this interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class Intent(BaseModel):
    # greeting | help | open_app | app_check | web_search | create_folder | system_info
    # | rescan_system | change_setting | run_workflow | unknown
    name: str
    confidence: float = 0.0
    language: str = "unknown"
    entities: dict[str, Any] = Field(default_factory=dict)
    provider: str = ""


class AIProvider(ABC):
    name: str = "base"
    is_local: bool = True

    @abstractmethod
    async def detect_intent(self, text: str) -> Intent:
        """Map a user utterance (any supported language) to a structured intent."""

    async def is_available(self) -> bool:
        return True

    def configure_wake(self, assistant_name: str, wake_word: str) -> None:
        """Tell the provider which name/wake word prefixes to ignore. Optional."""
