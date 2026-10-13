"""Events published on the in-process bus.

A part never imports another part — the event type is the only shared
knowledge.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SpeechStarted:
    """VAD detected voice onset. Treated as barge-in while the assistant speaks."""


@dataclass(frozen=True)
class PartialTranscript:
    """In-progress ASR result for the current turn. May be revised."""

    text: str


@dataclass(frozen=True)
class TurnEnded:
    """End-of-turn detected. Carries the final transcript."""

    transcript: str
