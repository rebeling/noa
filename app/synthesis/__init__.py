"""Synthesis part — text-to-speech.

Public surface: SynthesisService and postprocess_for_speech.

English uses the provider named by `NOA_TTS_PROVIDER` (`piper`, the
default, or `kokoro`). German always uses Piper, since Kokoro ships no
German voice. One provider per language is built lazily on first use, so
heavy imports (piper, kokoro_onnx) never run at import time.
"""

import os
from collections.abc import AsyncGenerator

from app.contracts import TTSProvider
from app.synthesis._postprocess import postprocess_for_speech

__all__ = ["SynthesisService", "postprocess_for_speech"]

_PROVIDER = os.environ.get("NOA_TTS_PROVIDER", "piper").lower()
_DE_PIPER_VOICE = os.environ.get("NOA_PIPER_DE_VOICE", "voices/de_DE-thorsten-medium.onnx")
_LANGS = ("en", "de")


def _build_provider(language: str) -> TTSProvider:
    if language == "en" and _PROVIDER == "kokoro":
        from app.synthesis._kokoro import KokoroTTS

        tts: TTSProvider = KokoroTTS()
    else:
        from app.synthesis._piper import PiperTTS

        tts = PiperTTS(_DE_PIPER_VOICE) if language == "de" else PiperTTS()
    print(f"[tts] {language} provider={type(tts).__name__} ready={tts.is_ready()}")
    return tts


class SynthesisService:
    """Renders speech with the provider for the active session language."""

    def __init__(self, language: str = "en") -> None:
        self._providers: dict[str, TTSProvider] = {}
        self._language = language if language in _LANGS else "en"

    def set_language(self, language: str) -> None:
        if language in _LANGS:
            self._language = language

    def _get_tts(self) -> TTSProvider:
        if self._language not in self._providers:
            self._providers[self._language] = _build_provider(self._language)
        return self._providers[self._language]

    def warmup(self) -> None:
        self._get_tts().warmup()

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        async for chunk in self._get_tts().synthesize_stream(text):
            yield chunk
