"""User-editable settings (assistant name, wake word, listening, startup). Stored in SQLite."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from .db import Database

SETTINGS_KEY = "user_settings"


class UserSettings(BaseModel):
    assistant_name: str = Field(default="NOVA", min_length=1, max_length=24)
    wake_word: str = Field(default="Hey NOVA", min_length=2, max_length=40)
    continuous_listening: bool = False  # takes effect when voice arrives (Phase 5)
    startup_mode: Literal["silent", "active"] = "active"  # takes effect with Windows startup (Phase 12)
    ai_mode: Literal["hybrid", "llm", "rules"] = "hybrid"
    ai_model: str = Field(default="qwen3:4b", min_length=1, max_length=80, pattern=r"^[A-Za-z0-9._:/\-]+$")
    stt_language: Literal["ur", "hi", "en", "auto"] = "ur"
    tts_voice: str = Field(default="ur_PK-fasih-medium", max_length=80, pattern=r"^[A-Za-z0-9_\-]+$")
    speak_responses: Literal["voice_only", "always", "never"] = "voice_only"

    @field_validator("assistant_name", "wake_word")
    @classmethod
    def _clean_text(cls, value: str) -> str:
        value = " ".join(value.split())
        # Letters (any script), digits, spaces and a little punctuation; nothing that could break prompts or UI.
        if not value or not all(ch.isalnum() or ch in " .-'" for ch in value):
            raise ValueError("Sirf haroof, numbers, space, '.', '-' aur ' allowed hain")
        return value


class UserSettingsUpdate(BaseModel):
    assistant_name: str | None = None
    wake_word: str | None = None
    continuous_listening: bool | None = None
    startup_mode: Literal["silent", "active"] | None = None
    ai_mode: Literal["hybrid", "llm", "rules"] | None = None
    ai_model: str | None = None
    stt_language: Literal["ur", "hi", "en", "auto"] | None = None
    tts_voice: str | None = None
    speak_responses: Literal["voice_only", "always", "never"] | None = None


def load_user_settings(db: Database, default_name: str = "NOVA") -> UserSettings:
    raw = db.get_setting(SETTINGS_KEY)
    if raw:
        try:
            return UserSettings.model_validate_json(raw)
        except ValidationError:
            pass  # corrupted/old value: fall back to defaults rather than refusing to start
    return UserSettings(assistant_name=default_name, wake_word=f"Hey {default_name}")


def apply_update(current: UserSettings, update: UserSettingsUpdate) -> UserSettings:
    changes: dict[str, Any] = update.model_dump(exclude_none=True)
    return UserSettings.model_validate({**current.model_dump(), **changes})


def save_user_settings(db: Database, settings: UserSettings) -> None:
    db.set_setting(SETTINGS_KEY, json.dumps(settings.model_dump(), ensure_ascii=False))
