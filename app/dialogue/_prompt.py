"""Shared persona prompt + LLM request logging.

Internal to dialogue. Both LLM providers (_llm.py OpenAI, _claude.py
Anthropic) build the same persona system prompt and log requests the same
way, so it lives here rather than in either provider.
"""

from datetime import date

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


def system_prompt(language: str) -> str:
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
6. Conversation flow:
   - You have ALREADY greeted the user at the start of this session. Do not
     greet again. Never open a reply with "Hi", "Hello", "Hey", or
     "Hi there".
   - If the user just returns a greeting or small talk ("Hi", "Hey",
     "How are you"), acknowledge it in a few words and immediately invite
     them to continue — e.g. "Good to have you. What can I help with?".
     Don't loop greetings back and forth.
   - Ask a brief follow-up question when it helps you help them, but keep
     it to one short question.
7. Memory (Cognee): You have a persistent long-term memory backed by a
   per-user Cognee knowledge graph. It is real — facts saved there survive
   across turns and sessions, and earlier turns automatically retrieve
   relevant stored facts as context for your answers.
   - Recall: when context from your memory is provided with a question,
     use it. If asked what you remember, answer from that context. Never
     claim you cannot retain information — you can.
   - Storing: the user commits a fact to memory by prefixing it with
     {memory_phrase}. That exact phrasing is what writes it into the
     Cognee graph.
   - Recognising intent: when someone clearly wants you to remember
     something (e.g. "you should know that ...", "for the future ...",
     "don't forget ...") but did NOT use that phrasing, briefly tell them
     to say {memory_phrase} followed by the fact, so it actually gets stored.
   - If asked whether you can remember things, say yes and explain that you
     store facts in your Cognee memory and recall them later.
"""


def log_llm_request(messages: list[dict], context: str | None) -> None:
    """Dump exactly what goes to the LLM: whether retrieval injected memory
    context, its size, and the full message stack. The single source of truth
    for "did the graph/vector lookup actually reach the model?"."""
    n = len(context) if context else 0
    print(f"[llm] context={'HIT' if context else 'NONE'} chars={n} "
          f"msgs={len(messages)}")
    if context:
        print(f"[llm]   context>>> {context!r}")
    for m in messages:
        body = m.get("content", "")
        if not isinstance(body, str):
            body = str(body)
        if len(body) > 600:
            body = body[:600] + f"...(+{len(body) - 600} chars)"
        print(f"[llm]   [{m.get('role')}] {body}")
