"""Faster-Whisper ASR — internal to speech_input."""

import time

import numpy as np
from faster_whisper import WhisperModel

from app.contracts import ASRProvider


_SUPPORTED_LANGS = {"en", "de"}


class WhisperASR(ASRProvider):
    """Two-model ASR: 'tiny' greedy for live partials (must stay realtime),
    'small' beam-search for the FINAL transcript only.

    Rationale: partials fire many times per turn and gate barge-in, so they
    need RTF < 1 — 'tiny' delivers that. The final transcript runs once per
    turn and feeds fact ingest + the LLM, where 'tiny' garbled German
    ("merk dir dass" -> "Merkt ihr das") and broke wake-phrase matching.
    'small' runs there: one slow decode per turn is acceptable; per-partial
    latency is not. The 'small' model loads lazily on the first final so a
    pure-partial warmup never pays for it."""

    def __init__(self, language: str = "en") -> None:
        self._fast = WhisperModel("tiny", device="cpu", compute_type="int8")
        self._accurate = None  # 'small', built lazily on first final
        self._language = language if language in _SUPPORTED_LANGS else "en"

    def _get_accurate(self):
        if self._accurate is None:
            self._accurate = WhisperModel(
                "small", device="cpu", compute_type="int8"
            )
        return self._accurate

    def set_language(self, language: str) -> None:
        if language in _SUPPORTED_LANGS:
            self._language = language

    def transcribe(self, audio: bytes, partial: bool) -> str:
        """Transcribe raw PCM int16 bytes. Partials use the fast 'tiny'
        model with greedy decoding; the final uses 'small' with beam search
        for accuracy. `partial=True` also drops timestamps."""
        audio_int16 = np.frombuffer(audio, dtype=np.int16)
        audio_float32 = audio_int16.astype(np.float32) / 32768.0
        audio_secs = len(audio_float32) / 16000.0

        model = self._fast if partial else self._get_accurate()
        beam_size = 1 if partial else 5

        t0 = time.perf_counter()
        segments, _info = model.transcribe(
            audio_float32,
            language=self._language,
            beam_size=beam_size,
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
