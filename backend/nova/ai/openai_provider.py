"""OpenAI as NOVA's brain (optional, Phase 13C): the same request parser and JSON contract as the local model.

Used only when the user saved an OpenAI API key (and chose OpenAI or "auto"). The model's JSON is validated exactly
like the local model's (parse_model_output), so the cloud model can only choose known capabilities, never how risky
they are. The key comes from the encrypted secret store for each request and never enters logs or replies.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable

import httpx

from ..language import detect_language
from .base import AIProvider, ConversationTurn, Intent, Understanding
from .ollama import SYSTEM_PROMPT, build_prompt, parse_model_output

OPENAI_URL = "https://api.openai.com/v1"
DEFAULT_CHAT_MODEL = "gpt-4o-mini"
# complete_json: the local model gets the schema through Ollama's "format"; OpenAI's JSON mode gets it in words.
JSON_SYSTEM = "{system}\n\nReply with one JSON object that follows this JSON schema:\n{schema}"


class OpenAIError(Exception):
    """A readable (Roman Urdu) reason: wrong key, no credit, no internet..."""


def explain(exc: Exception) -> str:
    if isinstance(exc, OpenAIError):
        return str(exc)
    if isinstance(exc, httpx.TimeoutException):
        return "OpenAI ne waqt par jawab nahi diya"
    if isinstance(exc, httpx.TransportError):
        return "OpenAI tak raabta nahi (internet?)"
    return f"OpenAI ka jawab samajh nahi aaya ({type(exc).__name__})"


def raise_for(r: httpx.Response) -> None:
    if r.status_code < 400:
        return
    try:
        message = str(r.json().get("error", {}).get("message") or "")[:160]
    except ValueError:
        message = ""
    reason = {401: "OpenAI API key ghalat ya band hai", 403: "Is key ko ye model istemal karne ki ijazat nahi",
              404: "Ye OpenAI model nahi mila", 429: "OpenAI ki had ya credit khatam (429)"}.get(r.status_code)
    raise OpenAIError(reason or f"OpenAI error {r.status_code}" + (f": {message}" if message else ""))


class OpenAIProvider(AIProvider):
    name = "openai"
    is_local = False

    def __init__(self, key: Callable[[], str | None], model: Callable[[], str] | None = None,
                 base_url: str = OPENAI_URL, timeout: float = 20.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._key = key
        self._model = model or (lambda: DEFAULT_CHAT_MODEL)
        self.base_url = base_url
        self.timeout = timeout
        self._transport = transport
        self.last_error: str | None = None

    @property
    def model(self) -> str:
        return self._model()

    @property
    def configured(self) -> bool:
        return bool(self._key())

    def _client(self, timeout: float | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=timeout or self.timeout, transport=self._transport,
                                 headers={"Authorization": f"Bearer {self._key() or ''}"})

    async def is_available(self) -> bool:
        return self.configured

    async def check(self) -> tuple[bool, str]:
        """Is the key accepted? (lists models - costs nothing)."""
        if not self.configured:
            return False, "OpenAI API key save nahi"
        try:
            async with self._client(timeout=10.0) as client:
                r = await client.get("/models")
            raise_for(r)
            ids = {m.get("id") for m in r.json().get("data", [])}
        except (httpx.HTTPError, OpenAIError, ValueError) as exc:
            return False, explain(exc)
        missing = [m for m in (self.model,) if ids and m not in ids]
        return (False, f"Key theek, lekin model '{missing[0]}' is account mein nahi") if missing else (True, "Key theek")

    async def _chat(self, messages: list[dict[str, str]], max_tokens: int, timeout: float | None) -> str:
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": 0,
                                   "max_completion_tokens": max_tokens, "response_format": {"type": "json_object"}}
        async with self._client(timeout=timeout) as client:
            r = await client.post("/chat/completions", json=payload)
            if r.status_code == 400 and "temperature" in r.text:  # some models only allow the default
                payload.pop("temperature")
                r = await client.post("/chat/completions", json=payload)
        raise_for(r)
        return str(r.json()["choices"][0]["message"]["content"] or "")

    async def detect_intent(self, text: str) -> Intent:
        return (await self.understand(text)).intents[0]

    async def understand(self, text: str, context: list[ConversationTurn] | None = None,
                         memories: list[str] | None = None, style_hint: str | None = None, *,
                         timeout: float | None = None) -> Understanding:
        started = time.perf_counter()
        prompt = build_prompt(text, context, memories, style_hint)
        content = await self._chat([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
                                   max_tokens=400, timeout=timeout)
        intents, answer = parse_model_output(content, detect_language(text), self.name, text)
        return Understanding(intents=intents, provider=f"{self.name}:{self.model}",
                             latency_ms=int((time.perf_counter() - started) * 1000), answer=answer)

    async def complete_json(self, system: str, prompt: str, schema: dict[str, Any], max_tokens: int = 600,
                            num_ctx: int = 8192, timeout: float = 120.0) -> dict[str, Any]:
        """Same contract as the local model's complete_json: one JSON object (only shown/spoken, never executed)."""
        instruction = JSON_SYSTEM.format(system=system, schema=json.dumps(schema))
        content = await self._chat([{"role": "system", "content": instruction}, {"role": "user", "content": prompt}],
                                   max_tokens=max_tokens, timeout=timeout)
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("model reply is not a JSON object")
        return data
