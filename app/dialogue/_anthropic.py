"""Anthropic LLM provider — internal to dialogue.

The Messages API takes the system prompt as a separate argument, so
history here holds only user/assistant turns.
"""

from collections.abc import AsyncGenerator

from anthropic import AsyncAnthropic

from app.contracts import LLMProvider
from app.core.config import settings
from app.dialogue._prompt import log_llm_request, system_prompt

# Replies are short per the persona prompt; this only prevents mid-sentence cuts.
_MAX_TOKENS = 1024


class AnthropicLLM(LLMProvider):
    def __init__(self, language: str = "en") -> None:
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._system = system_prompt(language)
        self._history: list[dict] = []

    async def warmup(self) -> None:
        await self._client.models.retrieve(settings.LLM_MODEL)

    def set_language(self, language: str) -> None:
        self._system = system_prompt(language)

    async def respond_stream(self, user_text: str) -> AsyncGenerator[str, None]:
        self._history.append({"role": "user", "content": user_text})
        log_llm_request([{"role": "system", "content": self._system}, *self._history])
        collected: list[str] = []
        async with self._client.messages.stream(
            model=settings.LLM_MODEL,
            max_tokens=_MAX_TOKENS,
            system=self._system,
            messages=self._history,
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    collected.append(text)
                    yield text
        self._history.append({"role": "assistant", "content": "".join(collected)})
