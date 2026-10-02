"""AI Provider Manager: keeps providers swappable (local rule-based now, Ollama/cloud later)."""

from __future__ import annotations

from .base import AIProvider, Intent
from .rule_based import RuleBasedProvider


class ProviderManager:
    def __init__(self, active: str = "rule_based") -> None:
        self._providers: dict[str, AIProvider] = {}
        self.register(RuleBasedProvider())
        self._fallback = "rule_based"
        self._active = active if active in self._providers else self._fallback

    def register(self, provider: AIProvider) -> None:
        self._providers[provider.name] = provider

    @property
    def active(self) -> AIProvider:
        return self._providers[self._active]

    def set_active(self, name: str) -> None:
        if name not in self._providers:
            raise KeyError(f"Unknown AI provider: {name}")
        self._active = name

    def describe(self) -> list[dict[str, object]]:
        return [
            {"name": p.name, "is_local": p.is_local, "active": p.name == self._active}
            for p in self._providers.values()
        ]

    async def detect_intent(self, text: str) -> Intent:
        provider = self.active
        if provider.name != self._fallback and not await provider.is_available():
            provider = self._providers[self._fallback]
        return await provider.detect_intent(text)
