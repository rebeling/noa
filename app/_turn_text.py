"""Pure text helpers for the dialogue orchestrator — no I/O, no state.

Greeting pool and the TTS pronunciation pass. Split out of orchestrator.py
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
