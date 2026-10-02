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
    ACTION_EXECUTED = "ACTION_EXECUTED"
    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    VERIFICATION_PASSED = "VERIFICATION_PASSED"
    NOVA_RESPONSE = "NOVA_RESPONSE"
    TASK_FAILED = "TASK_FAILED"
    TASK_COMPLETED = "TASK_COMPLETED"


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
