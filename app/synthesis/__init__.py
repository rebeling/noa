"""Synthesis part — text-to-speech.

Public surface: SynthesisService. The English provider is selected at
runtime via `NOA_TTS_PROVIDER=kokoro|piper|styletts2` (default: kokoro).
German always uses Piper (Kokoro v1.0 ships no German voice), via a
German voice file configured by `NOA_PIPER_DE_VOICE`.

Language-aware: the service keeps one provider per language and picks
the active one from the session language (set at construction and
switchable mid-session via set_language). Each provider is in its own
underscore-private module and shares the TTSProvider contract.

Lazy loading: heavy imports (kokoro_onnx, piper, styletts2) are
deferred to the first synth/warmup call so `import app.synthesis`
stays cheap regardless of which provider is selected.
"""

import os
from collections.abc import AsyncGenerator

__all__ = ["SynthesisService"]


_PROVIDER = os.environ.get("NOA_TTS_PROVIDER", "kokoro").lower()
# Kokoro v1.0 has no German voice, so German always goes through Piper.
_DE_PIPER_VOICE = os.environ.get(
    "NOA_PIPER_DE_VOICE", "voices/de_DE-thorsten-medium.onnx"
)


class SynthesisService:
    """Owns one TTS provider per language and renders with the active
    one. The English provider follows NOA_TTS_PROVIDER; German uses
    Piper. Providers load lazily on first use for their language, so a
    session that never speaks German never loads the German model."""

    def __init__(self, language: str = "en") -> None:
        # provider instances keyed by language code, built lazily
        self._providers: dict[str, object] = {}
        self._language = language if language in ("en", "de") else "en"

    def set_language(self, language: str) -> None:
        """Switch the active synthesis language. The provider for the new
        language is built on its next use, not here."""
        if language in ("en", "de"):
            self._language = language

    def _build_provider(self, language: str):
        """Construct the TTS provider for `language`. English honors
        NOA_TTS_PROVIDER (default Kokoro); German uses Piper with a
        German voice. Falls back to Kokoro if a provider can't init."""
        if language == "de":
            from app.synthesis._piper import PiperTTS

            candidate = PiperTTS(_DE_PIPER_VOICE)
            if candidate.is_ready():
                print(f"[tts] de provider=piper voice={_DE_PIPER_VOICE}")
                return candidate
            print("[tts] de Piper not ready, falling back to kokoro (no German voice)")
            from app.synthesis._kokoro import KokoroTTS

            return KokoroTTS()
        # English (or anything else): the configured provider.
        name = _PROVIDER
        print(f"[tts] en requested provider={name}")
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
            print(f"[tts] en using provider={name}")
            return candidate
        if name != "kokoro":
            print(f"[tts] provider={name} not ready, falling back to kokoro")
        from app.synthesis._kokoro import KokoroTTS
        return KokoroTTS()

    def _get_tts(self, language: str | None = None):
        """Return the provider for `language` (defaults to the active
        session language), building it on first use."""
        lang = language or self._language
        if lang not in ("en", "de"):
            lang = "en"
        if lang not in self._providers:
            self._providers[lang] = self._build_provider(lang)
        return self._providers[lang]

    def warmup(self) -> None:
        """Warm the active language's provider. Safe to call repeatedly."""
        self._get_tts().warmup()

    def precache(self, text: str) -> bytes:
        """Synth `text` once with the active provider, return WAV."""
        return self._get_tts().precache(text)

    def synthesize(self, text: str) -> bytes:
        """Render `text` with the active language's provider. Returns
        empty bytes if TTS failed to init."""
        return self._get_tts().synthesize(text)

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """Stream WAV chunks from the active language's provider."""
        async for chunk in self._get_tts().synthesize_stream(text):
            yield chunk
