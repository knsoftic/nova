"""Behavior Layer (Phase 10): the user's estimated state -> NOVA's tone; habits -> workflow suggestions.

- The estimate (words, conversation, voice) is shown as an estimate and lives in RAM only.
- The reply style follows the user's choice (auto / short / detailed); "auto" adapts to the estimate.
- Habits are what the user opened and which commands ran, kept like the history; a routine seen on several days
  becomes a suggestion ("Inka workflow bana doon?"), saved only after "haan".
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from ..agents.computer import ControlOutcome
from ..agents.prepared import Prepared, Reply
from ..ai.base import Intent
from ..db import Database
from .estimator import BehaviorEstimator, Estimate, Turn
from .patterns import LOOKBACK_DAYS, OPEN_KINDS, Routine, describe, find_routines, part_of_day, summary
from .signals import VoiceFeatures, is_simple_command
from .style import LLM_HINTS, REPLY_STYLES, choose_style, shape

NAME = "Behavior Layer"
BEHAVIOR_INTENTS = {"set_reply_style", "show_patterns"}
# Talking to NOVA about NOVA itself is not a habit worth learning.
NOT_HABITS = {"greeting", "help", "thanks", "unknown", "repeat_last", "forget_memory", "clear_history",
              "delete_workflow", "show_patterns", "set_reply_style", "search_history", "recall_memory"}
STYLE_WORDS = {"short": "chhote", "detailed": "tafseel se", "auto": "halat ke mutabiq (khud)"}
Progress = Callable[[str], Awaitable[None]]


def site_key(url: str) -> str:
    return re.sub(r"^(?:https?://)?(?:www\.)?", "", url.strip().lower()).split("/")[0]


class BehaviorLayer:
    def __init__(
        self,
        db: Database,
        settings: Callable[[], Any],
        save_settings: Callable[[dict[str, Any]], Awaitable[Any]] | None = None,
        resolve_app: Callable[[str], str | None] = lambda name: None,
        estimator: BehaviorEstimator | None = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.db = db
        self.settings = settings
        self.save_settings = save_settings
        self.resolve_app = resolve_app
        self.estimator = estimator or BehaviorEstimator()
        self.now = now
        self.suggested = False  # at most one routine suggestion per session

    # ------------------------------------------------------------------ estimate and tone

    def estimate(self, text: str, turns: list[Turn], voice: VoiceFeatures | None = None) -> Estimate:
        s = self.settings()
        if not s.emotion_awareness:
            return Estimate(simple=is_simple_command(text))
        return self.estimator.estimate(text, turns, voice if s.voice_signals else None)

    def style(self, estimate: Estimate) -> str:
        return choose_style(estimate, self.settings().reply_style)

    @staticmethod
    def llm_hint(style: str) -> str | None:
        return LLM_HINTS.get(style)

    @staticmethod
    def shape(response: str, style: str, *, outcome: str, intents: list[str], simple: bool) -> tuple[str, str | None]:
        return shape(response, style, outcome=outcome, intents=intents, simple=simple)

    # ------------------------------------------------------------------ habits

    def record(self, task_id: str, intent: Intent) -> None:
        """Called for steps that really ran."""
        if not self.settings().learn_patterns or intent.name in NOT_HABITS:
            return
        self.db.add_usage("command", intent.name, task_id)
        kind = OPEN_KINDS.get(intent.name)
        e = intent.entities
        if kind == "app" and (app := str(e.get("app") or "").strip()):
            self.db.add_usage(kind, self.resolve_app(app) or app, task_id)
        elif kind == "website" and (url := str(e.get("url") or "").strip()):
            self.db.add_usage(kind, site_key(url), task_id)
        elif kind == "project" and (project := str(e.get("project") or "").strip()):
            self.db.add_usage(kind, project.lower(), task_id)

    def _since(self) -> str:
        return (self.now() - timedelta(days=LOOKBACK_DAYS)).isoformat(timespec="seconds")

    def _covered(self) -> list[set[tuple[str, str]]]:
        covered = []
        for w in self.db.list_workflows():
            covered.append({(s["kind"], site_key(s["value"]) if s["kind"] == "website" else
                             s["value"].lower() if s["kind"] == "project" else s["value"]) for s in w["steps"]})
        return covered

    def routines(self) -> list[Routine]:
        return find_routines(self.db.list_usage(self._since()), self.now(), self._covered(),
                             self.db.declined_routines())

    def routine_to_suggest(self) -> Routine | None:
        s = self.settings()
        if self.suggested or not (s.learn_patterns and s.suggest_routines):
            return None
        found = self.routines()
        return found[0] if found else None

    def routine_name(self, routine: Routine) -> str:
        base = part_of_day(routine.hour)
        for name in (base, f"{base} routine", f"{base} 2", f"{base} 3"):
            if self.db.get_workflow(name) is None:
                return name
        return f"{base} {routine.days}"

    def suggestion(self, routine: Routine, name: str) -> str:
        labels = routine.labels
        things = ", ".join(labels[:-1]) + f" aur {labels[-1]}"
        return (f"Main ne dekha hai aap aksar {part_of_day(routine.hour)} {things} ek saath kholte hain "
                f"({routine.days} din). Inka '{name}' workflow bana doon? Phir bas \"{name} start karo\" kahein. "
                "(haan/nahi)")

    def patterns(self) -> dict[str, Any]:
        s = self.settings()
        data = summary(self.db.list_usage(self._since()), self.now())
        data["learning"] = s.learn_patterns
        data["routines"] = [{"key": r.key, "name": self.routine_name(r), "labels": r.labels, "days": r.days,
                             "hour": r.hour} for r in self.routines()] if s.learn_patterns else []
        return data

    # ------------------------------------------------------------------ "chhote jawab diya karo", "meri aadatein batao"

    async def prepare(self, intent: Intent, progress: Progress) -> Prepared | Reply:
        if intent.name == "show_patterns":
            return Prepared("Aadatein dikhana", "patterns")
        style = str(intent.entities.get("style") or "")
        if style not in REPLY_STYLES:
            return Reply("Jawab kaise chahiye — chhote ya tafseel se? (maslan \"chhote jawab diya karo\")")
        if self.settings().reply_style == style:
            return Reply(f"Jawab pehle se {STYLE_WORDS[style]} hain.")
        return Prepared(f"Jawab ka andaz: {STYLE_WORDS[style]}", "setting:reply_style", data={"style": style})

    async def run(self, intent: Intent, prepared: Prepared, approved: bool, progress: Progress) -> ControlOutcome:
        if intent.name == "show_patterns":
            if not self.settings().learn_patterns:
                return ControlOutcome("Aadatein seekhna band hai (Settings → Andaz aur aadatein).", "show_patterns", True,
                                      "not_applicable")
            data = self.patterns()
            text = describe(data)
            if data["routines"]:
                r = data["routines"][0]
                text += f"\nRoutine: {', '.join(r['labels'])} ({r['days']} din, {r['name']})."
            return ControlOutcome(text, "show_patterns", True, "not_applicable")
        style = prepared.data["style"]
        if self.save_settings is None:
            return ControlOutcome("Settings save nahi ho sakin.", "set_reply_style", False, "failed")
        await self.save_settings({"reply_style": style})
        ok = self.settings().reply_style == style
        return ControlOutcome(f"Theek hai, ab se jawab {STYLE_WORDS[style]} dunga." +
                              (" (Verify: Settings mein save hai.)" if ok else " Lekin setting save nahi hui."),
                              "set_reply_style", ok, "passed" if ok else "failed")
