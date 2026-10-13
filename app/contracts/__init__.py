"""Shared contracts — the only package a pipeline part may import
besides `app.bus`. Holds interfaces and event types, no logic."""

from app.contracts.audio import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH, AudioChunk
from app.contracts.events import PartialTranscript, SpeechStarted, TurnEnded
from app.contracts.providers import ASRProvider, LLMProvider, TTSProvider, VADProvider

__all__ = [
    "AudioChunk",
    "SAMPLE_RATE",
    "SAMPLE_WIDTH",
    "CHANNELS",
    "SpeechStarted",
    "PartialTranscript",
    "TurnEnded",
    "VADProvider",
    "ASRProvider",
    "LLMProvider",
    "TTSProvider",
]
