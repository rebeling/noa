"""Piper TTS — fast CPU ONNX voices. Internal to synthesis.

Voice files (.onnx + .onnx.json) live in `voices/`; `make voices` fetches
them. Piper renders a short reply in 50–200ms on a laptop CPU.
"""

import asyncio
import io
import os
import time
import wave
from collections.abc import AsyncGenerator
from pathlib import Path

from app.contracts import TTSProvider

_DEFAULT_VOICE = os.environ.get("NOA_PIPER_VOICE", "voices/en_GB-jenny_dioco-medium.onnx")


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buffer.getvalue()


class PiperTTS(TTSProvider):
    def __init__(self, model_path: str = _DEFAULT_VOICE) -> None:
        self._piper = None
        self._sample_rate = 22050
        if not Path(model_path).exists():
            print(f"[tts] Piper voice missing: {model_path} — run `make voices`")
            return
        t0 = time.perf_counter()
        try:
            from piper.voice import PiperVoice

            self._piper = PiperVoice.load(model_path)
            self._sample_rate = self._piper.config.sample_rate
            print(f"[tts init] Piper loaded in {(time.perf_counter()-t0)*1000:.0f}ms "
                  f"model={model_path} sr={self._sample_rate}")
        except Exception as e:  # noqa: BLE001
            print(f"[tts] Piper init failed: {e}")

    def is_ready(self) -> bool:
        return self._piper is not None

    def warmup(self) -> None:
        if not self._piper:
            return
        t0 = time.perf_counter()
        list(self._piper.synthesize("hi."))
        print(f"[tts warmup] {(time.perf_counter()-t0)*1000:.0f}ms")

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """One WAV chunk per sentence. Inference runs off the event loop so
        VAD, barge-in and LLM token reads keep flowing while a segment renders."""
        if not self._piper or not text:
            return
        t0 = time.perf_counter()
        chunks = await asyncio.to_thread(lambda: list(self._piper.synthesize(text)))
        t_synth = (time.perf_counter() - t0) * 1000
        for idx, ac in enumerate(chunks):
            audio_ms = len(ac.audio_int16_bytes) / 2 / self._sample_rate * 1000
            print(f"[tts stream] piper chunk={idx} synth={t_synth:.0f}ms audio={audio_ms:.0f}ms")
            yield _pcm_to_wav(ac.audio_int16_bytes, self._sample_rate)
