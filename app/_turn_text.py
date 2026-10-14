"""Pure text helpers for the orchestrator: greeting pool and LLM-stream
segmenting for TTS. No I/O, no state."""

import random
import re

# Sentence ends always split. Before the first segment is out we also split
# at the first clause boundary once FIRST_SEGMENT_MIN_CHARS are buffered, so
# the first audio lands after ~15–25 chars instead of a whole sentence.
_SENTENCE_END = re.compile(r"[.!?]\s+")
_CLAUSE_END = re.compile(r"[,;:—–]\s+")
FIRST_SEGMENT_MIN_CHARS = 12


def split_segment(buffer: str, first: bool) -> tuple[str | None, str]:
    """Pop one speakable segment off the front of `buffer`.

    Returns (segment, rest). segment is None when no boundary is buffered
    yet. `first=True` enables the clause-boundary split."""
    match = _SENTENCE_END.search(buffer)
    if first:
        clause = _CLAUSE_END.search(buffer, FIRST_SEGMENT_MIN_CHARS)
        if clause is not None and (match is None or clause.end() < match.end()):
            match = clause
    if match is None:
        return None, buffer
    return buffer[: match.end()].strip(), buffer[match.end() :]


_GREETINGS = {
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


def greeting(language: str) -> str:
    """A random greeting in `language` (falls back to English)."""
    return random.choice(_GREETINGS.get(language, _GREETINGS["en"]))


# Acknowledgements people make while listening. Hearing only these while
# Noa speaks is not a request to stop.
_BACKCHANNEL = {
    "ok", "okay", "hm", "hmm", "mhm", "mm", "mmm", "uh", "uh-huh", "huh", "ah", "aha", "oh",
    "yeah", "yep", "yes", "right", "sure", "cool", "nice", "wow",
    "ja", "jo", "genau", "gut", "klar", "stimmt", "achso", "ach", "so", "äh", "ähm",
}  # fmt: skip
_WORD = re.compile(r"[\wäöüß'-]+")


def is_interruption(text: str) -> bool:
    """Is a transcript heard while Noa speaks a real turn?

    Noise, barks and coughs transcribe to nothing or a stray character;
    backchannels are listening noises. Anything else takes the floor."""
    words = [w for w in _WORD.findall(text.lower()) if len(w) > 1]
    return any(w not in _BACKCHANNEL for w in words)
