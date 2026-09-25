"""AI provider architecture.

MANISK is provider-agnostic: any OpenAI-compatible Chat Completions API
works. Known-good configurations:

- NVIDIA NIM (Nemotron):  base_url=https://integrate.api.nvidia.com/v1
                         model=meta/llama-3.1-nemotron-70b-instruct
- OpenAI:                base_url=https://api.openai.com/v1
- Groq:                  base_url=https://api.groq.com/openai/v1
- Together:              base_url=https://api.together.xyz/v1
- Ollama (local):        base_url=http://127.0.0.1:11434/v1  (no key needed)
- vLLM / LM Studio:      base_url=http://<host>/v1

Credentials come ONLY from environment variables and are NEVER returned to
the frontend, never logged. If no provider is configured the registry
reports `configured=False` and the orchestrator runs in honest Local Mode.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import AsyncIterator, Optional

import httpx

from ..config import Settings
from ..observability import get_logger, log

logger = get_logger("mansik.ai.provider")


@dataclass
class Provider:
    kind: str          # "openai-compatible"
    base_url: str
    api_key: Optional[str]
    model: str
    timeout: float
    max_retries: int
    max_tokens: int
    temperature: float

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.model)

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _payload(self, messages: list[dict], *, stream: bool, max_tokens: int | None, temperature: float | None) -> dict:
        return {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": self.temperature if temperature is None else temperature,
        }

    async def chat(self, messages: list[dict], *, max_tokens: int | None = None, temperature: float | None = None) -> str:
        """Non-streaming completion with retry/backoff on 429/5xx."""
        payload = self._payload(messages, stream=False, max_tokens=max_tokens, temperature=temperature)
        attempt = 0
        while True:
            attempt += 1
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url.rstrip('/')}/chat/completions",
                        headers=self._headers(), json=payload,
                    )
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"] or ""
                if resp.status_code in (429, 500, 502, 503, 504) and attempt <= self.max_retries:
                    await asyncio.sleep(min(2 ** attempt, 8))
                    continue
                raise ProviderError(f"Provider returned HTTP {resp.status_code}.", status=resp.status_code)
            except httpx.TimeoutException:
                if attempt <= self.max_retries:
                    continue
                raise ProviderError("Provider timed out.", status=504)
            except httpx.HTTPError as exc:
                if attempt <= self.max_retries:
                    await asyncio.sleep(min(2 ** attempt, 8))
                    continue
                raise ProviderError(f"Provider connection failed: {type(exc).__name__}.", status=502)

    async def stream_chat(
        self, messages: list[dict], *, max_tokens: int | None = None, temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """Streaming completion — yields text deltas."""
        payload = self._payload(messages, stream=True, max_tokens=max_tokens, temperature=temperature)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", f"{self.base_url.rstrip('/')}/chat/completions",
                headers=self._headers(), json=payload,
            ) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread())[:500]
                    raise ProviderError(f"Provider returned HTTP {resp.status_code}.", status=resp.status_code)
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0].get("delta", {})
                        if delta.get("content"):
                            yield delta["content"]
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue


class ProviderError(Exception):
    def __init__(self, message: str, *, status: int = 500):
        super().__init__(message)
        self.status = status


class ProviderRegistry:
    """Primary provider + optional fallback (e.g. Nemotron → local Ollama)."""

    def __init__(self, primary: Provider | None, fallback: Provider | None = None):
        self.primary = primary
        self.fallback = fallback

    @property
    def configured(self) -> bool:
        return self.primary is not None and self.primary.is_configured

    async def chat(self, messages: list[dict], **kwargs) -> str:
        last_error: Exception | None = None
        for provider in (self.primary, self.fallback):
            if provider is None or not provider.is_configured:
                continue
            try:
                return await provider.chat(messages, **kwargs)
            except ProviderError as exc:
                last_error = exc
                log(logger, "warning", "provider failed, trying fallback",
                    provider=provider.model, error=str(exc))
        if last_error is not None:
            raise last_error
        raise ProviderNotConfiguredError()

    async def stream_chat(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        try:
            if self.primary and self.primary.is_configured:
                buffer: list[str] = []
                async for delta in self.primary.stream_chat(messages, **kwargs):
                    buffer.append(delta)
                    yield delta
                return
        except ProviderError as exc:
            log(logger, "warning", "primary provider stream failed", error=str(exc))
            if self.fallback is None or not self.fallback.is_configured:
                raise
        # fallback (non-streamed, emitted as one delta for simplicity)
        if self.fallback and self.fallback.is_configured:
            text = await self.fallback.chat(messages, **kwargs)
            if text:
                yield text
            return
        raise ProviderNotConfiguredError()

    @classmethod
    def from_settings(cls, settings: Settings) -> "ProviderRegistry":
        primary = None
        if settings.ai_base_url and settings.ai_model:
            primary = Provider(
                kind="openai-compatible",
                base_url=settings.ai_base_url,
                api_key=settings.ai_api_key,
                model=settings.ai_model,
                timeout=settings.ai_timeout_seconds,
                max_retries=settings.ai_max_retries,
                max_tokens=settings.ai_max_tokens,
                temperature=settings.ai_temperature,
            )
        fallback = None
        if settings.ai_fallback_base_url and settings.ai_fallback_model:
            fallback = Provider(
                kind="openai-compatible",
                base_url=settings.ai_fallback_base_url,
                api_key=settings.ai_fallback_api_key,
                model=settings.ai_fallback_model,
                timeout=settings.ai_timeout_seconds,
                max_retries=settings.ai_max_retries,
                max_tokens=settings.ai_max_tokens,
                temperature=settings.ai_temperature,
            )
        return cls(primary=primary, fallback=fallback)


class ProviderNotConfiguredError(Exception):
    """Raised when no AI provider is configured — surfaced honestly."""

    def __init__(self):
        super().__init__(
            "No AI provider configured. Set MANISK_AI_BASE_URL, MANISK_AI_API_KEY (if required) "
            "and MANISK_AI_MODEL (e.g. NVIDIA NIM for Nemotron, OpenAI, Groq, Together, or a local Ollama)."
        )
