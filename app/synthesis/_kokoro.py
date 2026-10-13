"""Kokoro ONNX TTS — optional English provider. Internal to synthesis.

Richer voice than Piper but 600–1300ms per segment on CPU. Needs
`kokoro-v1.0.onnx` and `voices-v1.0.bin` in the repo root (`make kokoro`).
"""

import io
import time
from collections.abc import AsyncGenerator

import numpy as np
import soundfile as sf

from app.contracts import TTSProvider


def _samples_to_wav(samples: np.ndarray, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    sf.write(buffer, samples, sample_rate, format="WAV")
    return buffer.getvalue()


class KokoroTTS(TTSProvider):
    def __init__(
        self,
        model_path: str = "kokoro-v1.0.onnx",
        voices_path: str = "voices-v1.0.bin",
        voice: str = "af_sky",
        speed: float = 1.1,
    ) -> None:
        self._voice = voice
        self._speed = speed
        self._kokoro = None
        t0 = time.perf_counter()
        try:
            from kokoro_onnx import Kokoro

            self._kokoro = Kokoro(model_path, voices_path)
            print(f"[tts init] Kokoro loaded in {(time.perf_counter()-t0)*1000:.0f}ms "
                  f"voice={voice} speed={speed}")
        except Exception as e:  # noqa: BLE001
            print(f"[tts] Kokoro init failed: {e} — run `make kokoro`")

    def is_ready(self) -> bool:
        return self._kokoro is not None

    def warmup(self) -> None:
        if not self._kokoro:
            return
        t0 = time.perf_counter()
        self._kokoro.create("hi.", voice=self._voice, speed=self._speed, lang="en-us")
        print(f"[tts warmup] {(time.perf_counter()-t0)*1000:.0f}ms")

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        if not self._kokoro or not text:
            return
        t0 = time.perf_counter()
        idx = 0
        async for samples, sample_rate in self._kokoro.create_stream(
            text, voice=self._voice, speed=self._speed, lang="en-us"
        ):
            audio_ms = len(samples) / sample_rate * 1000
            print(f"[tts stream] kokoro chunk={idx} "
                  f"since_start={(time.perf_counter()-t0)*1000:.0f}ms audio={audio_ms:.0f}ms")
            idx += 1
            yield _samples_to_wav(samples, sample_rate)
