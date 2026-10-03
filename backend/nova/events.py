"""Real-time event system. Every subscriber (UI WebSocket, tests) gets every published event."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EventType(str, Enum):
    SYSTEM_READY = "SYSTEM_READY"
    STATE_CHANGED = "STATE_CHANGED"
    NOVA_LISTENING = "NOVA_LISTENING"
    NOVA_THINKING = "NOVA_THINKING"
    TASK_STARTED = "TASK_STARTED"
    INTENT_DETECTED = "INTENT_DETECTED"
    AGENT_STARTED = "AGENT_STARTED"
    AGENT_WORKING = "AGENT_WORKING"
    PERMISSION_REQUIRED = "PERMISSION_REQUIRED"
    PERMISSION_DECIDED = "PERMISSION_DECIDED"
    ACTION_EXECUTED = "ACTION_EXECUTED"
    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    VERIFICATION_PASSED = "VERIFICATION_PASSED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    NOVA_RESPONSE = "NOVA_RESPONSE"
    TASK_FAILED = "TASK_FAILED"
    TASK_COMPLETED = "TASK_COMPLETED"
    DISCOVERY_STARTED = "DISCOVERY_STARTED"
    DISCOVERY_COMPLETED = "DISCOVERY_COMPLETED"
    DISCOVERY_FAILED = "DISCOVERY_FAILED"
    SETTINGS_CHANGED = "SETTINGS_CHANGED"
    PLAN_CREATED = "PLAN_CREATED"
    STEP_COMPLETED = "STEP_COMPLETED"
    AI_FALLBACK = "AI_FALLBACK"
    AI_STATUS = "AI_STATUS"
    VOICE_STATUS = "VOICE_STATUS"
    VOICE_TRANSCRIBED = "VOICE_TRANSCRIBED"
    WAKE_WORD_DETECTED = "WAKE_WORD_DETECTED"
    NOVA_SPEAK = "NOVA_SPEAK"
    MEMORY_CHANGED = "MEMORY_CHANGED"
    BEHAVIOR_ESTIMATED = "BEHAVIOR_ESTIMATED"
    SELF_TEST = "SELF_TEST"
    BUG_LOGGED = "BUG_LOGGED"
    ADMIN_DECISION = "ADMIN_DECISION"
    RETRY = "RETRY"
    SETUP_PROGRESS = "SETUP_PROGRESS"


class NovaState(str, Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    PLANNING = "PLANNING"
    WORKING = "WORKING"
    WAITING_FOR_PERMISSION = "WAITING_FOR_PERMISSION"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class NovaEvent(BaseModel):
    type: EventType
    timestamp: str = Field(default_factory=utc_now_iso)
    task_id: str | None = None
    agent: str | None = None
    message: str | None = None  # human-readable (Roman Urdu) line for the activity feed
    data: dict[str, Any] = Field(default_factory=dict)


class EventBus:
    def __init__(self, history_size: int = 200) -> None:
        self._subscribers: set[asyncio.Queue[NovaEvent]] = set()
        self._history: deque[NovaEvent] = deque(maxlen=history_size)

    def subscribe(self) -> asyncio.Queue[NovaEvent]:
        queue: asyncio.Queue[NovaEvent] = asyncio.Queue(maxsize=500)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[NovaEvent]) -> None:
        self._subscribers.discard(queue)

    def history(self) -> list[NovaEvent]:
        return list(self._history)

    def clear_history(self) -> None:
        """When the user deletes their history, the events replayed to a reconnecting UI go too."""
        self._history.clear()

    async def publish(self, event: NovaEvent) -> None:
        self._history.append(event)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # A stalled client must not block NOVA; drop its oldest event instead.
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
