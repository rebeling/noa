"""OpenAI LLM provider — internal to dialogue.

Owns the persona system prompt and per-session conversation history.
"""

from datetime import date

from openai import AsyncOpenAI

from app.contracts import LLMProvider
from app.core.config import settings

_PERSONA_NAME = "Noa"
# Map a session language code to the name used in the prompt directive.
_LANG_NAMES = {"de": "German", "en": "English"}

# The wake-phrase a user speaks to store a fact, per language. Must match the
# phrases the orchestrator's _FACT_WAKE_RE actually triggers on, so Noa never
# tells a user a phrasing that won't fire ingestion.
_MEMORY_PHRASE = {
    "de": '"Merk dir, dass ..."',
    "en": '"Remember that ..." (or "Note that ...")',
}


def _system_prompt(language: str) -> str:
    lang_name = _LANG_NAMES.get(language, "English")
    memory_phrase = _MEMORY_PHRASE.get(language, _MEMORY_PHRASE["en"])
    today = date.today().isoformat()
    return f"""
Your name is {_PERSONA_NAME}.
Today's date is {today}.
Follow these rules strictly:
1. Identity: Always identify as {_PERSONA_NAME} if asked.
2. Brevity: Keep responses very short and conversational (1-2 sentences max).
3. Tone: Professional yet friendly and efficient.
4. Constraints:
   - Never use lists or bullet points.
   - Never say "asterisk" or "bold".
   - Do not mention being an AI or large language model.
5. Language: Always answer in {lang_name}, regardless of the input language.
6. Memory: You can remember facts and recall them later.
   - Storing: a user stores a fact by prefixing it with {memory_phrase}.
     That exact phrasing is what commits it to your long-term memory.
   - Recognising intent: when someone clearly wants you to remember
     something (e.g. "you should know that ...", "for the future ...",
     "don't forget ...") but did NOT use that phrasing, briefly tell them
     to say {memory_phrase} followed by the fact, so it actually gets stored.
   - If asked whether you can remember things, say yes and explain how.
     Never claim you cannot retain information.
"""


class OpenAILLM(LLMProvider):
    def __init__(self, language: str = "en") -> None:
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._history = [
            {"role": "system", "content": _system_prompt(language)}
        ]

    def set_language(self, language: str) -> None:
        """Swap the reply language mid-session by rewriting the system
        prompt in place. Conversation history is preserved."""
        self._history[0] = {
            "role": "system", "content": _system_prompt(language)
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
        completion = await self._client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
        )
        reply = completion.choices[0].message.content or ""
        self._history.append({"role": "assistant", "content": reply})
        return reply
