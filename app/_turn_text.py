"""Pure text helpers for the dialogue orchestrator — no I/O, no state.

Greeting pool, LLM-stream segmenting for TTS, and the TTS pronunciation pass. Split out of orchestrator.py
so that module is just session wiring + event routing. Orchestrator-level
(not a pipeline part), so it does not touch app.contracts/app.bus.
"""

import re

# Pronunciation overrides for the TTS path. Empty by default — add
# entries here only if Kokoro mispronounces a specific name/term.
TTS_PRONUNCIATION: dict[str, str] = {}


def apply_tts_pronunciation(text: str) -> str:
    if not TTS_PRONUNCIATION:
        return text
    for src, dst in TTS_PRONUNCIATION.items():
        text = re.sub(rf"\b{re.escape(src)}\b", dst, text)
    return text



# Segmenting the LLM token stream for TTS. Sentence ends always split.
# Before the first segment has been emitted we additionally split at the
# earliest clause boundary (comma, semicolon, colon, dash) once at least
# FIRST_SEGMENT_MIN_CHARS are buffered — a ~15–25 char first segment makes
# Kokoro's first audio chunk land in ~0.3–0.5s instead of a whole sentence.
_SENTENCE_END = re.compile(r"[.!?]\s+")
_CLAUSE_END = re.compile(r"[,;:—–]\s+")
FIRST_SEGMENT_MIN_CHARS = 12


def split_segment(buffer: str, first: bool) -> tuple[str | None, str]:
    """Pop one speakable segment off the front of `buffer`.

    Returns (segment, rest). segment is None when no boundary is buffered
    yet (rest is then the unchanged buffer). `first=True` enables the
    clause-boundary split described above."""
    match = _SENTENCE_END.search(buffer)
    if first:
        clause = _CLAUSE_END.search(buffer, FIRST_SEGMENT_MIN_CHARS)
        if clause is not None and (match is None or clause.end() < match.end()):
            match = clause
    if match is None:
        return None, buffer
    return buffer[:match.end()].strip(), buffer[match.end():]


# Greeting pool per language — one picked at random per session so the
# assistant doesn't open with the same line every time.
GREETINGS = {
    "en": [
        "Hi, how can I help?",
        "Hey there — what's up?",
        "Hello! What can I do for you?",
        "Hi! What's on your mind?",
        "Hey! Ready when you are.",
        "Good to see you — how can I help?",
    ],
    "de": [
        "Hi, wie kann ich helfen?",
        "Hallo! Was gibt's?",
        "Hey, was kann ich für dich tun?",
        "Hallo! Was beschäftigt dich?",
        "Hi! Ich bin bereit, wenn du es bist.",
        "Schön, dass du da bist — wie kann ich helfen?",
    ],
}
