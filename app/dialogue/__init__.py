"""Dialogue part — LLM reply generation.

Public surface: DialogueService. The provider (OpenAI or Anthropic, picked
by settings.LLM_MODEL) is imported and built on first use so
`import app.dialogue` stays cheap.
"""

import time
from collections.abc import AsyncGenerator

from app.contracts import LLMProvider

__all__ = ["DialogueService"]


class DialogueService:
    """Owns the LLM provider for one session."""

    def __init__(self, language: str = "en") -> None:
        self._llm: LLMProvider | None = None
        self._language = language

    def _get_llm(self) -> LLMProvider:
        if self._llm is None:
            from app.core.config import settings

            if settings.LLM_MODEL.startswith("claude-"):
                from app.dialogue._anthropic import AnthropicLLM

                self._llm = AnthropicLLM(language=self._language)
            else:
                from app.dialogue._openai import OpenAILLM

                self._llm = OpenAILLM(language=self._language)
        return self._llm

    async def warmup(self) -> None:
        """Build the provider and open its connection. Safe to fire-and-forget."""
        t0 = time.perf_counter()
        try:
            await self._get_llm().warmup()
            print(f"[llm warmup] {(time.perf_counter() - t0)*1000:.0f}ms")
        except Exception as e:  # noqa: BLE001
            print(f"[llm warmup] failed: {e}")

    def set_language(self, language: str) -> None:
        self._language = language
        if self._llm is not None:
            self._llm.set_language(language)

    async def respond_stream(self, user_text: str) -> AsyncGenerator[str, None]:
        async for chunk in self._get_llm().respond_stream(user_text):
            yield chunk
