"""User-editable settings (assistant name, wake word, listening, startup). Stored in SQLite."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from .db import Database

SETTINGS_KEY = "user_settings"
FORBIDDEN_PROJECT_ROOTS = tuple(os.path.normcase(p) for p in (
    r"C:\Windows", r"C:\Program Files", r"C:\Program Files (x86)", r"C:\ProgramData"))


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
    search_engine: Literal["google", "bing", "duckduckgo"] = "google"  # for visible searches in NOVA's browser
    browser_channel: Literal["chrome", "msedge"] = "chrome"  # installed browser NOVA drives (own profile)
    # Code project folders the File/Coding agents may use (besides Desktop, Documents, Downloads, ...).
    project_folders: list[str] = Field(default_factory=lambda: [r"C:\xampp\htdocs"], max_length=10)
    # Conversation history is deleted after this many days (0 = kept until the user deletes it).
    history_days: Literal[30, 90, 365, 0] = 90
    # Behavior layer (Phase 10): reply style, the (estimated) communication state, learned habits.
    reply_style: Literal["auto", "short", "detailed"] = "auto"
    emotion_awareness: bool = True  # estimate the user's state and adapt the tone
    voice_signals: bool = True  # include speaking speed/loudness/pitch (measured live, never stored)
    show_estimate: bool = True  # show the estimate ("Andaza: ...") in the UI
    learn_patterns: bool = True  # remember which apps/websites/projects are opened and when
    suggest_routines: bool = True  # offer a workflow when the same things are opened together on several days

    @field_validator("project_folders")
    @classmethod
    def _check_project_folders(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        # realpath: Windows may report short 8.3 names ("QADRIL~1") for the same folder.
        home = os.path.normcase(os.path.realpath(Path.home()))
        temp = os.path.normcase(os.path.realpath(tempfile.gettempdir()))
        for raw in value:
            path = os.path.normpath(raw.strip().strip("\"'"))
            low = os.path.normcase(os.path.realpath(path)) if re.match(r"^[a-zA-Z]:\\", path + "\\") else path.lower()
            if not re.match(r"^[a-z]:\\", low + "\\"):
                raise ValueError("Poora folder path dein, maslan C:\\xampp\\htdocs")
            if len(low.rstrip("\\")) <= 2:
                raise ValueError("Poori drive project folder nahi ho sakti")
            # AppData holds app data and browser logins; only its Temp folder (scratch space) is acceptable.
            in_temp = low == temp or low.startswith(temp + "\\")
            if any(low == f or low.startswith(f + "\\") for f in FORBIDDEN_PROJECT_ROOTS) or (
                    "\\appdata" in low and not in_temp):
                raise ValueError("Windows, Program Files ya AppData project folder nahi ho sakte")
            if low in (home, os.path.normcase(os.path.dirname(home))):
                raise ValueError("Poora user folder nahi — sirf projects wala folder dein")
            if low not in (os.path.normcase(c) for c in cleaned):
                cleaned.append(path)
        return cleaned

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
    search_engine: Literal["google", "bing", "duckduckgo"] | None = None
    browser_channel: Literal["chrome", "msedge"] | None = None
    project_folders: list[str] | None = None
    history_days: Literal[30, 90, 365, 0] | None = None
    reply_style: Literal["auto", "short", "detailed"] | None = None
    emotion_awareness: bool | None = None
    voice_signals: bool | None = None
    show_estimate: bool | None = None
    learn_patterns: bool | None = None
    suggest_routines: bool | None = None


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
