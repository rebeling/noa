"""Synthesis part — text-to-speech.

Public surface: SynthesisService. Provider selected at runtime via
`NOA_TTS_PROVIDER=kokoro|piper|styletts2` (default: kokoro). Each
provider is in its own underscore-private module and shares the
TTSProvider contract from app.contracts.

Lazy loading: heavy imports (kokoro_onnx, piper, styletts2) are
deferred to the first synth/warmup call so `import app.synthesis`
stays cheap regardless of which provider is selected.
"""

import os
from collections.abc import AsyncGenerator

__all__ = ["SynthesisService"]


_PROVIDER = os.environ.get("NOA_TTS_PROVIDER", "kokoro").lower()


class SynthesisService:
    """Owns the TTS provider for one session. Provider is picked once
    at first use based on NOA_TTS_PROVIDER. Model load is deferred to
    the same call so import-time stays fast."""

    def __init__(self) -> None:
        self._tts = None  # built lazily — see _get_tts()
        self._provider_name = _PROVIDER

    def _get_tts(self):
        """Load the configured TTS provider on first use. Each branch
        does its own heavy import so unused providers stay out of
        memory. If the configured provider fails to initialize (missing
        package, missing model file, etc.), fall back to Kokoro so the
        session still produces audio."""
        if self._tts is not None:
            return self._tts
        name = self._provider_name
        print(f"[tts] requested provider={name}")
        candidate = None
        if name == "piper":
            from app.synthesis._piper import PiperTTS
            candidate = PiperTTS()
        elif name == "styletts2":
            from app.synthesis._styletts2 import StyleTTS2
            candidate = StyleTTS2()
        elif name == "kokoro":
            from app.synthesis._kokoro import KokoroTTS
            candidate = KokoroTTS()
        else:
            print(f"[tts] unknown provider '{name}', using kokoro")
        if candidate is not None and candidate.is_ready():
            self._tts = candidate
            print(f"[tts] using provider={name}")
            return self._tts
        if name != "kokoro":
            print(f"[tts] provider={name} not ready, falling back to kokoro")
        from app.synthesis._kokoro import KokoroTTS
        self._tts = KokoroTTS()
        self._provider_name = "kokoro"
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
        """Stream WAV chunks. Yields nothing if TTS failed to init."""
        async for chunk in self._get_tts().synthesize_stream(text):
            yield chunk
