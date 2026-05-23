"""Events published on the in-process bus.

Pipeline parts publish and subscribe to these. A part never imports
another part — the event type is the only shared knowledge.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SpeechStarted:
    """VAD detected voice onset. Synthesis treats this as barge-in."""


@dataclass(frozen=True)
class PartialTranscript:
    """In-progress ASR result for the current turn. May be revised."""

    text: str


@dataclass(frozen=True)
class FinalTranscript:
    """Committed ASR result for a completed turn."""

    text: str


@dataclass(frozen=True)
class TurnEnded:
    """Turn detector saw end-of-speech. Carries the final transcript."""

    transcript: str


@dataclass(frozen=True)
class ResponseText:
    """LLM-produced reply text, ready for synthesis."""

    text: str


@dataclass(frozen=True)
class PipelineError:
    """A part failed. Carries the originating part name and the error."""

    part: str
    error: str
