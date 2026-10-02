"""Speech input part — VAD + turn detection + ASR.

Public surface: SpeechInputService. Internals (_vad, _asr, _turn) are
private. No other pipeline part imports this package's internals.

Lazy loading: the heavy ASR import (parakeet_mlx) is deferred to
first transcribe() call, so `import app.speech_input` stays cheap and
the server boots fast. VAD and TurnDetector are pure-Python and light,
so they import at module scope.
"""

import os

from app.contracts import AudioChunk
from app.speech_input._turn import TurnDetector
from app.speech_input._vad import AmplitudeVAD

__all__ = ["SpeechInputService"]

_SUPPORTED_LANGS = {"en", "de"}


class SpeechInputService:
    """Owns VAD, turn detection, and ASR for one session.

    VAD + turn detection are ready immediately. The Parakeet model loads
    lazily on the first transcribe() call — construction is cheap.
    """

    def __init__(self, language: str = "en") -> None:
        self._vad = AmplitudeVAD()
        self._turn = TurnDetector()
        self._asr = None  # built lazily — see _get_asr()
        self._language = language if language in _SUPPORTED_LANGS else "en"

    def _get_asr(self):
        """Load the ASR provider on first use. The heavy model import +
        construction are deferred to here so boot stays fast. Parakeet TDT
        v3 on the Apple GPU via MLX — Apple Silicon only."""
        if self._asr is None:
            from app.speech_input._parakeet import ParakeetASR

            self._asr = ParakeetASR(language=self._language)
        return self._asr

    def set_language(self, language: str) -> None:
        """Switch transcription language mid-session. Cheap — only flips
        a flag on the loaded ASR; the model itself is multilingual.
        Unknown codes are ignored."""
        if language not in _SUPPORTED_LANGS:
            return
        self._language = language
        if self._asr is not None:
            self._asr.set_language(language)

    @property
    def is_speaking(self) -> bool:
        return self._turn.is_speaking

    def detect(self, chunk: AudioChunk) -> str | None:
        """Run VAD on `chunk`, update turn state.
        Returns 'start', 'end', or None."""
        confidence = self._vad.speech_confidence(chunk)
        return self._turn.on_confidence(confidence)

    def transcribe(self, audio: bytes, partial: bool) -> str:
        """Transcribe accumulated turn audio. Loads the ASR model on the
        first call."""
        return self._get_asr().transcribe(audio, partial)
