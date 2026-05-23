"""OpenAI LLM provider — internal to dialogue.

Owns the persona system prompt and per-session conversation history.
"""

from openai import AsyncOpenAI

from app.contracts import LLMProvider
from app.core.config import settings

_PERSONA_NAME = "Noa"
_SYSTEM_PROMPT = f"""
Your name is {_PERSONA_NAME}.
Follow these rules strictly:
1. Identity: Always identify as {_PERSONA_NAME} if asked.
2. Brevity: Keep responses very short and conversational (1-2 sentences max).
3. Tone: Professional yet friendly and efficient.
4. Constraints:
   - Never use lists or bullet points.
   - Never say "asterisk" or "bold".
   - Do not mention being an AI or large language model.
5. Language: Always answer in English, regardless of the input language.
"""


class OpenAILLM(LLMProvider):
    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._history = [{"role": "system", "content": _SYSTEM_PROMPT}]

    async def respond(self, user_text: str) -> str:
        self._history.append({"role": "user", "content": user_text})
        completion = await self._client.chat.completions.create(
            model="gpt-4o-mini",
            messages=self._history,
        )
        reply = completion.choices[0].message.content or ""
        self._history.append({"role": "assistant", "content": reply})
        return reply
