"""Pure text helpers for the dialogue orchestrator — no I/O, no state.

Question/recall routing, the fact wake-phrase, filler/greeting pools and the
TTS pronunciation pass. Split out of orchestrator.py so that module is just
session wiring + event routing. Orchestrator-level (not a pipeline part), so
it does not touch app.contracts/app.bus.
"""

import random
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


# First tokens that mark an utterance as a question worth a knowledge-graph
# lookup. Crude on purpose — swap this whole function for a classifier model
# if precision matters.
_QUESTION_WORDS = frozenset(
    "who what when where why how which whose whom "
    "is are am was were can could would should "
    "do does did will may might shall".split()
)

# Recall-intent phrasings that are NOT questions (no '?', no leading question
# word) but still want a memory lookup: imperatives ("tell me about ...",
# "remind me ...") and memory-directed verbs ("recall", "remember", "know
# about"). Without this, "tell me about Matthias" / "erzähl mir von ..." skip
# Cognee entirely and Noa answers from nothing — looking like it has no memory.
# Matched anywhere in the utterance, case-insensitively.
_RECALL_RE = re.compile(
    r"\b("
    r"tell me (?:about|what)|what do you (?:know|remember)|"
    r"do you (?:know|remember)|remind me|recall|"
    r"know about|remember about|"
    r"erz[äa]hl|erzaehl|was wei(?:ß|ss)t du|"
    r"erinnerst du|kennst du|wei(?:ß|ss)t du (?:noch|über|ueber)"
    r")\b",
    re.IGNORECASE,
)


def looks_like_question(text: str) -> bool:
    """Heuristic question detector. True if the utterance ends with '?'
    or opens with a question word. No model, no API call — the cheap
    routing gate that decides whether to hit Cognee."""
    t = text.strip().lower()
    if not t:
        return False
    if t.endswith("?"):
        return True
    if _RECALL_RE.search(t):
        return True
    first = t.split(None, 1)[0].strip(".,!?;:")
    return first in _QUESTION_WORDS


# Wake phrase that marks a spoken turn as "store this as a fact". Everything
# after the phrase is ingested. Matched case-insensitively at the start of the
# turn. Built as a regex (not a startswith list) because ASR transcribes the
# same spoken phrase with varying punctuation/filler — "Merk dir, dass …",
# "Merke dir: …", "Merk dir mal …" must all match. Groups:
#   - merk(e) dir  with optional " mal", then optional separator (",", ":",
#     " dass", " das") before the body.
#   - remember / note that  (English).
# ASR (Whisper) mangles the spoken German wake-phrase badly: "merk dir dass"
# comes back as "Merkt ihr das", "Merk, dir, dass", "Merke dir, dass", etc.
# So match loosely: merk/merkt/merke  +  dir/ihr  +  optional mal  +  optional
# dass/das, with stray commas/colons anywhere. English: remember (that) / note
# that. Trailing separators after the phrase are stripped before the body.
_FACT_WAKE_RE = re.compile(
    r"^\s*(?:"
    r"merk[te]?\s*,?\s*(?:dir|ihr)(?:\s+mal)?\s*,?\s*(?:dass|das)?"  # German + ASR variants
    r"|remember(?:\s+that)?"                                          # English
    r"|note\s+that"
    r")\b[\s,:]*",
    re.IGNORECASE,
)
# Spoken confirmation after a successful fact ingest, per language.
FACT_CONFIRM = {
    "en": "Got it. I'll remember that.",
    "de": "Verstanden. Ich merke es mir.",
}
# Spoken refusal when a non-admin tries to add a fact.
FACT_DENIED = {
    "en": "Sorry, only an admin can add facts. I can answer questions, though.",
    "de": "Nur ein Administrator kann Fakten hinzufügen. Fragen beantworte ich aber gern.",
}


def extract_fact(text: str) -> str | None:
    """If `text` opens with a fact wake-phrase, return the fact body
    (everything after the phrase). Otherwise None. Tolerant of ASR
    punctuation/word mangling — see _FACT_WAKE_RE."""
    m = _FACT_WAKE_RE.match(text)
    if not m:
        return None
    body = text[m.end():].strip().lstrip(",:; ").strip()
    return body or None


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

# Fillers: short natural phrases Noa says while thinking for a long answer.
# These provide immediate audio feedback (latency < 200ms) while the slow
# LLM/Cognee parts run in the background.
FILLERS = {
    "en": [
        "Let me see...",
        "One moment...",
        "Let me think about that...",
        "Hmm, let me check...",
        "Good question, let me look that up...",
        "Sure, give me a second...",
        "Okay, checking now...",
        "Right, let me find that...",
        "Just a moment...",
        "Let me pull that up...",
    ],
    "de": [
        "Lass mich kurz nachsehen...",
        "Einen Moment bitte...",
        "Ich schaue mal eben...",
        "Hm, lass mich kurz überlegen...",
        "Gute Frage, ich sehe mal nach...",
        "Klar, einen Augenblick...",
        "Okay, ich prüfe das...",
        "Moment, ich suche das...",
        "Sekunde, ich schaue...",
        "Das sehe ich mir kurz an...",
    ],
}


def pick_filler(pool: list[str], last: str | None) -> str:
    """Pick a filler, avoiding an immediate repeat of `last`. With a pool
    of >1 this guarantees the same line never plays twice in a row — the
    main thing that made the fillers feel canned."""
    if len(pool) > 1 and last is not None:
        choices = [p for p in pool if p != last]
        return random.choice(choices)
    return random.choice(pool)
