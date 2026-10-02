"""Parakeet-MLX ASR — internal to speech_input.

Runs NVIDIA's Parakeet TDT 0.6b v3 on the Apple GPU via Apple's MLX
framework. v3 is multilingual (EN + DE + 23 more, auto language detect),
so a single model serves every supported language. Parakeet TDT is
non-autoregressive — fast enough that one model covers both live partials
and the final transcript, with no tiny/small split.

Model: mlx-community/parakeet-tdt-0.6b-v3 (CC-BY-4.0). Downloaded from
Hugging Face on first use (~600MB) and cached.
"""

import time

import mlx.core as mx
import numpy as np
from parakeet_mlx import from_pretrained
from parakeet_mlx.audio import get_logmel

from app.contracts import ASRProvider

_MODEL_ID = "mlx-community/parakeet-tdt-0.6b-v3"


class ParakeetASR(ASRProvider):
    """Single multilingual Parakeet model for both partials and finals.

    v3 auto-detects language, so set_language() is only advisory and the
    model itself never switches — the method exists to satisfy the ASR
    interface (SpeechInputService.set_language calls it).
    """

    def __init__(self, language: str = "en") -> None:
        self._model = from_pretrained(_MODEL_ID)
        self._language = language
        # First inference pays MLX Metal-kernel compilation (~1.5s); warm it
        # on a short silent buffer here so the first real partial is already
        # fast (subsequent decodes run ~0.2 RTF).
        warm = np.zeros(16000, dtype=np.float32)
        mel = get_logmel(mx.array(warm), self._model.preprocessor_config)
        self._model.generate(mel)

    def set_language(self, language: str) -> None:
        # v3 detects language per utterance; kept for interface parity.
        self._language = language

    def transcribe(self, audio: bytes, partial: bool) -> str:
        """Transcribe raw PCM int16 (16kHz mono) in-memory — no temp file.

        Same single model + decode path for partial and final; Parakeet is
        fast enough that partials stay realtime without a lighter model.
        """
        audio_int16 = np.frombuffer(audio, dtype=np.int16)
        audio_float32 = audio_int16.astype(np.float32) / 32768.0
        audio_secs = len(audio_float32) / 16000.0

        t0 = time.perf_counter()
        mel = get_logmel(mx.array(audio_float32), self._model.preprocessor_config)
        t_pre = time.perf_counter()
        results = self._model.generate(mel)
        text = " ".join(r.text for r in results) if results else ""
        dt_total = time.perf_counter() - t0
        dt_decode = time.perf_counter() - t_pre
        kind = "partial" if partial else "final "
        print(
            f"[asr {kind}] {dt_total*1000:6.0f}ms total "
            f"(decode {dt_decode*1000:5.0f}ms) "
            f"audio={audio_secs:.2f}s RTF={dt_total/max(audio_secs,0.01):.2f} "
            f"chars={len(text)}"
        )
        return text.strip()
