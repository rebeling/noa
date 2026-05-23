"""Shared contracts — the ONLY package a pipeline part may import
besides `app.bus`. Holds interfaces and event types, no logic."""

from app.contracts.audio import (
    CHANNELS,
    SAMPLE_RATE,
    SAMPLE_WIDTH,
    AudioChunk,
)
from app.contracts.events import (
    FinalTranscript,
    PartialTranscript,
    PipelineError,
    ResponseText,
    SpeechStarted,
    TurnEnded,
)
from app.contracts.providers import (
    ASRProvider,
    LLMProvider,
    TTSProvider,
    VADProvider,
)

__all__ = [
    "AudioChunk",
    "SAMPLE_RATE",
    "SAMPLE_WIDTH",
    "CHANNELS",
    "SpeechStarted",
    "PartialTranscript",
    "FinalTranscript",
    "TurnEnded",
    "ResponseText",
    "PipelineError",
    "VADProvider",
    "ASRProvider",
    "LLMProvider",
    "TTSProvider",
]
