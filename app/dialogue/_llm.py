"""OpenAI LLM provider — internal to dialogue.

Holds per-session conversation history; persona prompt + request logging
are shared with the Claude provider via _prompt.
"""

from collections.abc import AsyncGenerator

from openai import AsyncOpenAI

from app.contracts import LLMProvider
from app.core.config import settings
from app.dialogue._prompt import log_llm_request, system_prompt


class OpenAILLM(LLMProvider):
    def __init__(self, language: str = "en") -> None:
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._history = [
            {"role": "system", "content": system_prompt(language)}
        ]

    def set_language(self, language: str) -> None:
        """Swap the reply language mid-session by rewriting the system
        prompt in place. Conversation history is preserved."""
        self._history[0] = {
            "role": "system", "content": system_prompt(language)
        }

    async def respond(self, user_text: str, context: str | None = None) -> str:
        # Persist only the raw user turn to history. Retrieved context is
        # transient: injected into this one request, never stored, so it
        # doesn't bloat or skew later turns.
        self._history.append({"role": "user", "content": user_text})
        if context:
            messages = self._history[:-1] + [
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nUser: {user_text}",
                }
            ]
        else:
            messages = self._history
        log_llm_request(messages, context)
        completion = await self._client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
        )
        reply = completion.choices[0].message.content or ""
        self._history.append({"role": "assistant", "content": reply})
        return reply

    async def respond_stream(
        self, user_text: str, context: str | None = None
    ) -> AsyncGenerator[str, None]:
        self._history.append({"role": "user", "content": user_text})
        if context:
            messages = self._history[:-1] + [
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nUser: {user_text}",
                }
            ]
        else:
            messages = self._history

        log_llm_request(messages, context)
        stream = await self._client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            stream=True,
        )
        collected_content = []
        async for chunk in stream:
            content = chunk.choices[0].delta.content or ""
            if content:
                collected_content.append(content)
                yield content

        full_reply = "".join(collected_content)
        self._history.append({"role": "assistant", "content": full_reply})
