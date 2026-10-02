"""Speech input part — VAD + turn detection + ASR.

Public surface: SpeechInputService. Internals (_vad, _asr, _turn) are
private. No other pipeline part imports this package's internals.

Lazy loading: the heavy ASR import (parakeet_mlx) is deferred to
first transcribe() call, so `import app.speech_input` stays cheap and
the server boots fast. AmplitudeVAD and TurnDetector are light and
import at module scope; SileroVAD loads its model inside _build_vad.
"""

import os

from app.contracts import SAMPLE_RATE, SAMPLE_WIDTH, AudioChunk
from app.speech_input._turn import TurnDetector
from app.speech_input._vad import AmplitudeVAD

__all__ = ["SpeechInputService"]

_SUPPORTED_LANGS = {"en", "de"}

# VAD thresholds per provider. Silero outputs a calibrated speech
# probability; the amplitude heuristic is scaled so 0.4 ≈ "voice".
_VAD_THRESHOLDS = {
    "silero": (0.5, 0.35),
    "amplitude": (0.4, 0.2),
}


def _build_vad(name: str):
    """Return (vad_provider, resolved_name). Falls back to amplitude if
    Silero cannot initialise (missing wheel/model) so a session always has
    a working VAD."""
    if name == "silero":
        try:
            from app.speech_input._silero import SileroVAD

            return SileroVAD(), "silero"
        except Exception as e:  # noqa: BLE001
            print(f"[vad  ] silero init failed ({e}); falling back to amplitude")
    return AmplitudeVAD(), "amplitude"


class SpeechInputService:
    """Owns VAD, turn detection, and ASR for one session.

    VAD + turn detection are ready immediately. The Parakeet model loads
    lazily on the first transcribe() call — construction is cheap.
    """

    def __init__(self, language: str = "en") -> None:
        requested = os.environ.get("NOA_VAD", "silero").lower()
        self._vad, vad_name = _build_vad(requested)
        start_conf, silence_conf = _VAD_THRESHOLDS[vad_name]
        self._turn = TurnDetector(start_conf, silence_conf)
        print(f"[vad  ] provider={vad_name} start>{start_conf} silence<{silence_conf}")
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
        """Run VAD on the newly received `chunk` (every byte, in order —
        Silero is stateful), update turn state.
        Returns 'start', 'end', or None."""
        confidence = self._vad.speech_confidence(chunk)
        audio_secs = len(chunk.data) / (SAMPLE_RATE * SAMPLE_WIDTH)
        return self._turn.on_confidence(confidence, audio_secs)

    def transcribe(self, audio: bytes, partial: bool) -> str:
        """Transcribe accumulated turn audio. Loads the ASR model on the
        first call."""
        return self._get_asr().transcribe(audio, partial)
