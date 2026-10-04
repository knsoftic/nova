"""Which language model answers: OpenAI (when the user chose it, or "auto" with a saved key) or local Ollama.

If OpenAI fails (no internet, wrong key, no credit), the same request goes to the local model when it is ready, so
NOVA keeps working. Agents (summaries, message drafts, code explanations) use this router too.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import httpx

from .base import ConversationTurn, Understanding
from .ollama import OllamaProvider
from .openai_provider import OpenAIError, OpenAIProvider, explain

log = logging.getLogger("nova.ai")

FAILURES = (httpx.HTTPError, OpenAIError, ValueError, KeyError, TypeError)


class LLMRouter:
    def __init__(self, ollama: OllamaProvider, openai: OpenAIProvider, choice: Callable[[], str]) -> None:
        self.ollama = ollama
        self.openai = openai
        self.choice = choice  # "auto" | "openai" | "ollama"

    @property
    def wants_openai(self) -> bool:
        choice = self.choice()
        return self.openai.configured and choice in ("auto", "openai")

    @property
    def primary(self) -> OllamaProvider | OpenAIProvider:
        return self.openai if self.wants_openai else self.ollama

    @property
    def name(self) -> str:
        return self.primary.name

    @property
    def model(self) -> str:
        return self.primary.model

    async def is_available(self) -> bool:
        return self.wants_openai or await self.ollama.is_available()

    async def understand(self, text: str, context: list[ConversationTurn] | None = None,
                         memories: list[str] | None = None, style_hint: str | None = None) -> Understanding:
        if self.wants_openai:
            try:
                result = await self.openai.understand(text, context, memories, style_hint)
                self.openai.last_error = None
                return result
            except FAILURES as exc:
                self.openai.last_error = explain(exc)
                log.warning("OpenAI understanding failed: %s", self.openai.last_error)
                if not await self.ollama.is_available():
                    raise
        return await self.ollama.understand(text, context, memories, style_hint=style_hint)

    async def complete_json(self, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 600,
                            num_ctx: int = 8192, timeout: float = 240.0) -> dict[str, Any]:
        if self.wants_openai:
            try:
                result = await self.openai.complete_json(system, prompt, schema, max_tokens=max_tokens,
                                                         timeout=min(timeout, 120.0))
                self.openai.last_error = None
                return result
            except FAILURES as exc:
                self.openai.last_error = explain(exc)
                log.warning("OpenAI completion failed: %s", self.openai.last_error)
                if not await self.ollama.is_available():
                    raise
        return await self.ollama.complete_json(system, prompt, schema, max_tokens=max_tokens, num_ctx=num_ctx,
                                               timeout=timeout)
