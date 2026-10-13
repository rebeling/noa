"""OpenAI LLM provider — internal to dialogue."""

from collections.abc import AsyncGenerator

from openai import AsyncOpenAI

from app.contracts import LLMProvider
from app.core.config import settings
from app.dialogue._prompt import log_llm_request, system_prompt


class OpenAILLM(LLMProvider):
    def __init__(self, language: str = "en") -> None:
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._history = [{"role": "system", "content": system_prompt(language)}]

    async def warmup(self) -> None:
        await self._client.models.retrieve(settings.LLM_MODEL)

    def set_language(self, language: str) -> None:
        self._history[0] = {"role": "system", "content": system_prompt(language)}

    async def respond_stream(self, user_text: str) -> AsyncGenerator[str, None]:
        self._history.append({"role": "user", "content": user_text})
        log_llm_request(self._history)
        stream = await self._client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=self._history,
            stream=True,
        )
        collected: list[str] = []
        async for chunk in stream:
            content = chunk.choices[0].delta.content or ""
            if content:
                collected.append(content)
                yield content
        self._history.append({"role": "assistant", "content": "".join(collected)})
