"""Abstract provider interfaces.

Each pipeline part depends on these, never on a concrete model class.
Swapping a model means writing a new implementation of one base.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from app.contracts.audio import AudioChunk


class VADProvider(ABC):
    """Voice activity detection over a chunk of audio."""

    @abstractmethod
    def speech_confidence(self, chunk: AudioChunk) -> float:
        """Return 0.0..1.0 confidence that `chunk` contains speech."""


class ASRProvider(ABC):
    """Speech-to-text transcription."""

    @abstractmethod
    def transcribe(self, audio: bytes, partial: bool) -> str:
        """Transcribe raw PCM `audio`. `partial=True` favors speed over
        accuracy for in-progress results."""


class LLMProvider(ABC):
    """Streaming reply generation. Implementations own conversation history."""

    @abstractmethod
    async def warmup(self) -> None:
        """Open the connection so the first turn skips connection setup."""

    @abstractmethod
    def set_language(self, language: str) -> None:
        """Switch the reply language mid-session, keeping history."""

    @abstractmethod
    def respond_stream(self, user_text: str) -> AsyncGenerator[str]:
        """Yield reply text chunks for `user_text`."""


class TTSProvider(ABC):
    """Text-to-speech synthesis."""

    @abstractmethod
    def is_ready(self) -> bool:
        """False when the model failed to load; synthesis then yields nothing."""

    @abstractmethod
    def warmup(self) -> None:
        """Run a tiny synthesis so the first real call is fast."""

    @abstractmethod
    def synthesize_stream(self, text: str) -> AsyncGenerator[bytes]:
        """Yield self-contained WAV chunks for `text` as they are rendered."""
