"""Faster-Whisper ASR — internal to speech_input."""

import time

import numpy as np
from faster_whisper import WhisperModel

from app.contracts import ASRProvider


_SUPPORTED_LANGS = {"en", "de"}


class WhisperASR(ASRProvider):
    def __init__(self, language: str = "en") -> None:
        # 'tiny' keeps RTF < 1 on CPU; 'base' was ~7x realtime, unusable
        # for live partials. Accuracy hit is acceptable for short turns.
        self._model = WhisperModel("tiny", device="cpu", compute_type="int8")
        self._language = language if language in _SUPPORTED_LANGS else "en"

    def set_language(self, language: str) -> None:
        if language in _SUPPORTED_LANGS:
            self._language = language

    def transcribe(self, audio: bytes, partial: bool) -> str:
        """Transcribe raw PCM int16 bytes. Greedy decoding and disabled
        cross-segment conditioning keep latency bounded; `partial=True`
        drops timestamps for the live partial path."""
        audio_int16 = np.frombuffer(audio, dtype=np.int16)
        audio_float32 = audio_int16.astype(np.float32) / 32768.0
        audio_secs = len(audio_float32) / 16000.0

        t0 = time.perf_counter()
        segments, _info = self._model.transcribe(
            audio_float32,
            language=self._language,
            beam_size=1,
            condition_on_previous_text=False,
            vad_filter=True,
            without_timestamps=partial,
        )
        t_decode = time.perf_counter()
        text = " ".join(segment.text for segment in segments)
        dt_total = time.perf_counter() - t0
        dt_decode = time.perf_counter() - t_decode
        kind = "partial" if partial else "final "
        print(
            f"[asr {kind}] {dt_total*1000:6.0f}ms total "
            f"(decode {dt_decode*1000:5.0f}ms) "
            f"audio={audio_secs:.2f}s RTF={dt_total/max(audio_secs,0.01):.2f} "
            f"chars={len(text)}"
        )
        return text.strip()
