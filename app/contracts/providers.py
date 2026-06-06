"""Abstract provider interfaces.

Each pipeline part depends on these abstractions, never on a concrete
model class. Swapping a model means writing a new implementation of one
of these bases — no other part changes.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from app.contracts.audio import AudioChunk


class VADProvider(ABC):
    """Voice activity detection over a chunk of audio."""

    @abstractmethod
    def speech_confidence(self, chunk: AudioChunk) -> float:
        """Return 0.0..1.0 confidence that `chunk` contains speech."""
        raise NotImplementedError


class ASRProvider(ABC):
    """Speech-to-text transcription."""

    @abstractmethod
    def transcribe(self, audio: bytes, partial: bool) -> str:
        """Transcribe raw PCM `audio`. `partial=True` favors speed over
        accuracy for in-progress results."""
        raise NotImplementedError


class LLMProvider(ABC):
    """Response generation from a user utterance."""

    @abstractmethod
    async def respond(self, user_text: str, context: str | None = None) -> str:
        """Produce a reply to `user_text`. Implementations own their own
        conversation history.

        `context` is optional retrieved knowledge (e.g. a knowledge-graph
        search result) the implementation may ground its answer on. It is
        transient per-turn — implementations must not persist it into
        conversation history.
        """
        raise NotImplementedError

    @abstractmethod
    async def respond_stream(
        self, user_text: str, context: str | None = None
    ) -> AsyncGenerator[str, None]:
        """Produce a streaming reply to `user_text` as an async generator
        yielding text chunks.

        Implementations must handle the same context/history rules as
        `respond`.
        """
        raise NotImplementedError


class TTSProvider(ABC):
    """Text-to-speech synthesis."""

    @abstractmethod
    def synthesize(self, text: str) -> bytes:
        """Render `text` to WAV-format audio bytes."""
        raise NotImplementedError
