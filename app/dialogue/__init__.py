"""Dialogue part — LLM response generation.

Public surface: DialogueService. Internal: _llm.

Lazy loading: the openai import and AsyncOpenAI client construction are
deferred to the first respond() call so `import app.dialogue` stays
cheap.
"""

__all__ = ["DialogueService"]


class DialogueService:
    """Owns the LLM provider for one session. The OpenAI client is
    built lazily on the first respond() call."""

    def __init__(self, language: str = "en") -> None:
        self._llm = None  # built lazily — see _get_llm()
        self._language = language

    def _get_llm(self):
        """Build the LLM provider on first use. Importing openai and
        constructing the client are both deferred to here."""
        if self._llm is None:
            from app.dialogue._llm import OpenAILLM

            self._llm = OpenAILLM(language=self._language)
        return self._llm

    def set_language(self, language: str) -> None:
        """Switch reply language. Updates the stored default and, if the
        LLM is already built, rewrites its system prompt in place."""
        self._language = language
        if self._llm is not None:
            self._llm.set_language(language)

    async def respond(self, user_text: str, context: str | None = None) -> str:
        """Generate a reply to `user_text`, optionally grounded on
        `context` (retrieved knowledge). Builds the OpenAI client on the
        first call."""
        return await self._get_llm().respond(user_text, context)
