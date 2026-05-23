"""Synthesis part — text-to-speech.

Public surface: SynthesisService. Internal: _kokoro.

Lazy loading: the kokoro_onnx import and model-file load are deferred
to the first synthesize()/synthesize_stream()/warmup() call so
`import app.synthesis` stays cheap.
"""

from collections.abc import AsyncGenerator

__all__ = ["SynthesisService"]


class SynthesisService:
    """Owns the TTS provider for one session. The Kokoro model loads
    lazily on the first synth/stream/warmup call."""

    def __init__(self) -> None:
        self._tts = None  # built lazily — see _get_tts()

    def _get_tts(self):
        """Load the TTS provider on first use. Importing kokoro_onnx and
        loading the model files are both deferred to here."""
        if self._tts is None:
            from app.synthesis._kokoro import KokoroTTS

            self._tts = KokoroTTS()
        return self._tts

    def warmup(self) -> None:
        """Force model load + a tiny dummy synth so the first real
        synth call doesn't pay cold-start cost. Safe to call repeatedly."""
        self._get_tts().warmup()

    def precache(self, text: str) -> bytes:
        """Synth `text` once, return WAV. Caller caches and replays."""
        return self._get_tts().precache(text)

    def synthesize(self, text: str) -> bytes:
        """Render `text` to one WAV blob. Returns empty bytes if TTS
        failed to init."""
        return self._get_tts().synthesize(text)

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """Stream WAV chunks as Kokoro produces them. Yields nothing if
        TTS failed to init."""
        async for chunk in self._get_tts().synthesize_stream(text):
            yield chunk
