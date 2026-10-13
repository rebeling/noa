"""Text post-processing for speech — internal to synthesis.

The LLM reply is written for a screen: it may carry markdown (**bold**,
*italics*, `code`, bullets), URLs, and the occasional wall of text. None
of that survives a text-to-speech pass gracefully — Kokoro will literally
voice asterisks, read a URL character by character, or ramble for 30s.

`postprocess_for_speech` is a single deterministic string transform that
runs ONCE on the full reply, between the LLM and TTS. It is pure string
work (no model, no API call) so it adds no measurable latency to the
reply path. Streaming is unaffected: the caller still hands the cleaned
string to synthesize_stream, which chunks it internally — see
SynthesisService.synthesize_stream.

Scope is deliberately small (this is a local voice assistant, not a
moderation system):
  - voice-friendliness: strip markdown markup, neutralize URLs, drop
    control chars, collapse whitespace.
  - brevity: cap the spoken length at a sentence boundary so a runaway
    reply doesn't become a 60-second monologue.
"""

import re

# Hard cap on spoken characters. Replies longer than this are truncated
# at the last sentence boundary before the cap (falling back to a word
# boundary). The system prompt already asks the LLM for 1-2 sentences;
# this is a backstop for when it ignores that.
_MAX_SPEECH_CHARS = 600

# Markdown / markup patterns, applied in order.
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)  # ```code block```
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")  # `code`
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")  # ![alt](url)
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")  # [text](url) -> text
_URL_RE = re.compile(r"https?://\S+|www\.\S+")  # bare URLs
_EMPHASIS_RE = re.compile(r"(\*{1,3}|_{1,3})(\S.*?\S|\S)\1")  # **b** *i* _x_
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)  # # heading
_BLOCKQUOTE_RE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)  # > quote
_BULLET_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+", re.MULTILINE)  # - item / 1. item
_STRAY_MARKUP_RE = re.compile(r"[*_`~#>|]+")  # leftover markup chars
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # control chars
_WS_RE = re.compile(r"\s+")
# Sentence boundary: punctuation followed by whitespace or end-of-string.
_SENTENCE_END_RE = re.compile(r"[.!?](?:\s|$)")


def _truncate_for_brevity(text: str, limit: int) -> str:
    """Trim `text` to <= limit chars, cutting at the last sentence end
    before the limit when possible, else the last word boundary, else a
    hard cut. Keeps a trailing period so TTS prosody closes cleanly."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    # Prefer the last full sentence inside the budget.
    ends = [m.end() for m in _SENTENCE_END_RE.finditer(head)]
    if ends:
        return head[: ends[-1]].strip()
    # No sentence break — cut at the last word boundary.
    cut = head.rsplit(" ", 1)[0].strip() or head.strip()
    if cut and cut[-1] not in ".!?":
        cut += "."
    return cut


def postprocess_for_speech(text: str) -> str:
    """Make an LLM reply safe and tight to speak aloud.

    Deterministic string transform: strips markdown, neutralizes URLs and
    links (keeps link text, drops the address), removes control chars,
    collapses whitespace, and caps length at a sentence boundary. Returns
    "" for empty/whitespace input. Never raises on normal text."""
    if not text:
        return ""

    # Drop code fences entirely (reading code aloud is noise).
    text = _CODE_FENCE_RE.sub(" ", text)
    # Inline code -> its contents.
    text = _INLINE_CODE_RE.sub(r"\1", text)
    # Images -> gone; links -> their visible text.
    text = _IMAGE_RE.sub(" ", text)
    text = _LINK_RE.sub(r"\1", text)
    # Bare URLs read terribly char-by-char — replace with a spoken token.
    text = _URL_RE.sub("link", text)
    # Emphasis -> inner text (run twice to catch nested/adjacent markers).
    text = _EMPHASIS_RE.sub(r"\2", text)
    text = _EMPHASIS_RE.sub(r"\2", text)
    # Structural markdown.
    text = _HEADING_RE.sub("", text)
    text = _BLOCKQUOTE_RE.sub("", text)
    text = _BULLET_RE.sub("", text)
    # Any leftover markup chars, then control chars.
    text = _STRAY_MARKUP_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    # Collapse all whitespace (incl. the newlines that joined bullets) to
    # single spaces so the reply speaks as flowing prose.
    text = _WS_RE.sub(" ", text).strip()

    return _truncate_for_brevity(text, _MAX_SPEECH_CHARS)
