"""StyleTTS2 — high-quality neural TTS, slower than Piper but more
expressive than Kokoro. Install: `uv add styletts2`.

Defers heavy torch import to first use. On CPU it's similar speed
to Kokoro; on CUDA/MPS it can hit <300ms first audio.
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


class StyleTTS2(TTSProvider):
    def __init__(self) -> None:
        self._tts = None
        self._sample_rate = 24000
        t0 = time.perf_counter()
        try:
            from styletts2 import tts as _styletts2_tts
            self._tts = _styletts2_tts.StyleTTS2()
            print(f"[tts init] StyleTTS2 loaded in {(time.perf_counter()-t0)*1000:.0f}ms")
        except ImportError:
            print("StyleTTS2 not installed. Run: uv add styletts2")
        except Exception as e:  # noqa: BLE001
            print(f"StyleTTS2 init failed: {e}")

    def is_ready(self) -> bool:
        return self._tts is not None

    def warmup(self) -> None:
        if not self._tts:
            return
        t0 = time.perf_counter()
        try:
            self._tts.inference("hi.")
            print(f"[tts warmup] {(time.perf_counter()-t0)*1000:.0f}ms")
        except Exception as e:  # noqa: BLE001
            print(f"[tts warmup] failed: {e}")

    def _synth_wav(self, text: str) -> bytes:
        if not self._tts or not text:
            return b""
        samples = self._tts.inference(text)
        if not isinstance(samples, np.ndarray):
            samples = np.asarray(samples, dtype=np.float32)
        return _samples_to_wav(samples, self._sample_rate)

    def precache(self, text: str) -> bytes:
        t0 = time.perf_counter()
        wav = self._synth_wav(text)
        print(f"[tts precache] {(time.perf_counter()-t0)*1000:.0f}ms "
              f"chars={len(text)} bytes={len(wav)}")
        return wav

    def synthesize(self, text: str) -> bytes:
        t0 = time.perf_counter()
        wav = self._synth_wav(text)
        print(f"[tts one-shot] {(time.perf_counter()-t0)*1000:.0f}ms "
              f"chars={len(text)} bytes={len(wav)}")
        return wav

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        if not self._tts or not text:
            return
        t0 = time.perf_counter()
        wav = self._synth_wav(text)
        print(f"[tts stream] styletts2 first={int((time.perf_counter()-t0)*1000)}ms "
              f"bytes={len(wav)}")
        yield wav
        print(f"[tts stream] done total={int((time.perf_counter()-t0)*1000)}ms "
              f"chars={len(text)}")
