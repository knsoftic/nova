"""AI Provider Manager: picks who understands a command and falls back safely.

Modes:
- hybrid (default): deterministic rules answer clear, short commands instantly; everything else
  (questions, long or unusual phrasing) goes to the local LLM.
- llm: every command goes to the local LLM.
- rules: the LLM is never used.
If the LLM is unavailable, slow or returns invalid output, the rules result is used and the
reason is reported - NOVA keeps working without a model.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Literal

import httpx

from .base import ConversationTurn, Understanding
from .ollama import OllamaProvider
from .rule_based import RuleBasedProvider

log = logging.getLogger("nova.ai")

AIMode = Literal["hybrid", "llm", "rules"]
AI_MODES: tuple[AIMode, ...] = ("hybrid", "llm", "rules")
HYBRID_RULE_CONFIDENCE = 0.8


class ProviderManager:
    def __init__(self, mode: AIMode = "hybrid", ollama: OllamaProvider | None = None) -> None:
        self.rules = RuleBasedProvider()
        self.ollama = ollama or OllamaProvider()
        self.mode: AIMode = mode if mode in AI_MODES else "hybrid"
        self.last_latency_ms: int | None = None
        self.last_provider: str | None = None

    def configure(self, mode: AIMode | None = None, model: str | None = None) -> None:
        if mode is not None:
            if mode not in AI_MODES:
                raise ValueError(f"Unknown AI mode: {mode}")
            self.mode = mode
        if model:
            self.ollama.model = model

    def configure_wake(self, assistant_name: str, wake_word: str) -> None:
        self.rules.configure_wake(assistant_name, wake_word)
        self.ollama.configure_wake(assistant_name, wake_word)

    async def status(self, refresh: bool = False) -> dict[str, Any]:
        ollama = await self.ollama.status(refresh=refresh)
        model_ready = ollama.reachable and self.ollama.model in ollama.models
        return {
            "mode": self.mode,
            "model": self.ollama.model,
            "model_ready": model_ready,
            "llm_in_use": self.mode != "rules" and model_ready,
            "ollama": ollama.model_dump(),
            "last_provider": self.last_provider,
            "last_latency_ms": self.last_latency_ms,
        }

    async def understand(self, text: str, context: list[ConversationTurn] | None = None,
                         memories: list[str] | None = None) -> Understanding:
        started = time.perf_counter()
        result = await self._understand(text, context, memories)
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        self.last_latency_ms, self.last_provider = result.latency_ms, result.provider
        return result

    async def _understand(self, text: str, context: list[ConversationTurn] | None,
                          memories: list[str] | None) -> Understanding:
        rules = await self.rules.understand(text, context)
        if self.mode == "rules":
            return rules
        if self.mode == "hybrid" and all(
            i.name != "unknown" and i.confidence >= HYBRID_RULE_CONFIDENCE for i in rules.intents
        ):
            return rules

        if not await self.ollama.is_available():
            rules.fallback_reason = "model_unavailable"
            return rules
        try:
            return await self.ollama.understand(text, context, memories)
        except httpx.TimeoutException:
            reason = "timeout"
        except (httpx.HTTPError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            log.warning("LLM understanding failed: %s", exc)
            reason = "invalid_output" if isinstance(exc, (json.JSONDecodeError, ValueError, KeyError, TypeError)) else "http_error"
        rules.fallback_reason = reason
        return rules
