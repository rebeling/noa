"""Anthropic (Claude) LLM provider — internal to dialogue.

Mirrors OpenAILLM's contract (respond / respond_stream / set_language) so
the two are swappable via settings.LLM_MODEL. The Anthropic Messages API
takes the persona prompt as a separate `system` argument rather than a
system-role message, so history here holds only user/assistant turns.
"""

from collections.abc import AsyncGenerator

from anthropic import AsyncAnthropic

from app.contracts import LLMProvider
from app.core.config import settings
from app.dialogue._prompt import log_llm_request, system_prompt

# Streaming responses need headroom; keep replies short per the persona, but
# don't truncate mid-sentence.
_MAX_TOKENS = 1024


class ClaudeLLM(LLMProvider):
    def __init__(self, language: str = "en") -> None:
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._system = system_prompt(language)
        # user/assistant turns only — system is passed separately each call.
        self._history: list[dict] = []

    def set_language(self, language: str) -> None:
        """Swap the reply language mid-session. History is preserved."""
        self._system = system_prompt(language)

    def _build_messages(self, user_text: str, context: str | None) -> list[dict]:
        # Persist only the raw user turn. Retrieved context is transient:
        # injected into this one request, never stored, so it doesn't bloat
        # or skew later turns. Mirrors OpenAILLM.
        self._history.append({"role": "user", "content": user_text})
        if context:
            return self._history[:-1] + [
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nUser: {user_text}",
                }
            ]
        return list(self._history)

    def _log(self, messages: list[dict], context: str | None) -> None:
        # Prepend the system prompt as a pseudo-message so the dump matches
        # OpenAILLM's (which carries system in history).
        log_llm_request(
            [{"role": "system", "content": self._system}, *messages], context
        )

    async def respond(self, user_text: str, context: str | None = None) -> str:
        messages = self._build_messages(user_text, context)
        self._log(messages, context)
        msg = await self._client.messages.create(
            model=settings.LLM_MODEL,
            max_tokens=_MAX_TOKENS,
            system=self._system,
            messages=messages,
        )
        reply = "".join(b.text for b in msg.content if b.type == "text")
        self._history.append({"role": "assistant", "content": reply})
        return reply

    async def respond_stream(
        self, user_text: str, context: str | None = None
    ) -> AsyncGenerator[str, None]:
        messages = self._build_messages(user_text, context)
        self._log(messages, context)
        collected: list[str] = []
        async with self._client.messages.stream(
            model=settings.LLM_MODEL,
            max_tokens=_MAX_TOKENS,
            system=self._system,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    collected.append(text)
                    yield text
        self._history.append(
            {"role": "assistant", "content": "".join(collected)}
        )
