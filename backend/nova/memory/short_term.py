"""Short-term memory: the current conversation and task. Kept in RAM only - gone after a long pause or a restart.

Holds the last few turns (context for the AI brain), the last command (for "dobara karo"), and an open
follow-up question NOVA asked ("Ye yaad rakhoon?", "Kaun se applications open karoon?") so the next answer is
understood as a reply to it.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from ..ai.base import ConversationTurn

IDLE_RESET_S = 30 * 60
MAX_TURNS = 4


@dataclass
class PendingQuestion:
    kind: str  # "remember" | "workflow_steps"
    question: str
    data: dict[str, Any] = field(default_factory=dict)
    asked_at: float = 0.0
    ttl_s: float = 180.0
    attempts: int = 0


class ShortTermMemory:
    def __init__(self, idle_reset_s: float = IDLE_RESET_S, clock: Callable[[], float] = time.monotonic) -> None:
        self.idle_reset_s = idle_reset_s
        self.clock = clock
        self._turns: deque[ConversationTurn] = deque(maxlen=MAX_TURNS)
        self.pending: PendingQuestion | None = None
        self.last_command: str | None = None  # the last real command (not an answer, not "dobara karo")
        self.last_response: str | None = None
        self.last_memory_id: int | None = None  # "ye bhool jao" right after "yaad rakho"
        self.declined: set[str] = set()  # suggestions the user said "nahi" to, not asked again this session
        self._last_at: float | None = None
        self._on_clear: list[Callable[[], None]] = []

    def on_clear(self, fn: Callable[[], None]) -> None:
        """Agents' own "current item" context ("isko" = the last file) is forgotten together with the conversation."""
        self._on_clear.append(fn)

    def touch(self) -> None:
        """Called for every command: after a long pause the old conversation no longer applies."""
        now = self.clock()
        if self._last_at is not None and now - self._last_at > self.idle_reset_s:
            self.clear()
        self._last_at = now

    def clear(self) -> None:
        self._turns.clear()
        self.pending = None
        self.last_command = self.last_response = None
        self.last_memory_id = None
        self.declined.clear()
        for fn in self._on_clear:
            fn()

    def turns(self) -> list[ConversationTurn]:
        return list(self._turns)

    def add_turn(self, user: str, assistant: str, command: bool = True) -> None:
        self._turns.append(ConversationTurn(user=user[:500], assistant=assistant[:500]))
        self.last_response = assistant
        if command:
            self.last_command = user

    def user_texts(self) -> list[str]:
        """What the user said in this conversation, newest first."""
        return [t.user for t in reversed(self._turns)]

    def ask(self, kind: str, question: str, data: dict[str, Any], ttl_s: float = 180.0, attempts: int = 0) -> None:
        self.pending = PendingQuestion(kind, question, data, self.clock(), ttl_s, attempts)

    def take_pending(self) -> PendingQuestion | None:
        """The open question, if still fresh. It is removed either way: one answer per question."""
        pending, self.pending = self.pending, None
        if pending is None or self.clock() - pending.asked_at > pending.ttl_s:
            return None
        return pending

    def snapshot(self) -> dict[str, Any]:
        idle = None if self._last_at is None else self.clock() - self._last_at
        return {
            "turns": [t.model_dump() for t in self._turns],
            "pending": self.pending.question if self.pending else None,
            "last_command": self.last_command,
            "idle_reset_min": int(self.idle_reset_s // 60),
            "resets_in_s": None if idle is None or not self._turns else max(0, int(self.idle_reset_s - idle)),
        }
