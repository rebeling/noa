"""Kokoro ONNX TTS — internal to synthesis.

Two entrypoints:
  - synthesize(text): one-shot, returns full WAV bytes. Kept for the
    ingestion/test path and as a fallback.
  - synthesize_stream(text): async generator yielding per-chunk WAV
    bytes as Kokoro produces them. Used by the live reply path so the
    client can start playback on the first chunk instead of waiting
    for the whole sentence.
"""

import io
import time
from collections.abc import AsyncGenerator

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

from app.contracts import TTSProvider


def _samples_to_wav(samples: np.ndarray, sample_rate: int) -> bytes:
    """Wrap float32 mono samples in an in-memory WAV container.
    Client decodes each chunk as its own WAV via WebAudio.decodeAudioData."""
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
        t0 = time.perf_counter()
        try:
            self._kokoro = Kokoro(model_path, voices_path)
            print(f"[tts init] Kokoro loaded in {(time.perf_counter()-t0)*1000:.0f}ms "
                  f"voice={voice} speed={speed}")
        except Exception as e:  # noqa: BLE001
            print(f"Kokoro init failed: {e}. TTS disabled.")
            self._kokoro = None

    def warmup(self) -> None:
        """Run a tiny synth so ONNX graphs / kernels are warm before
        the first user-visible call. Idempotent."""
        if not self._kokoro:
            return
        t0 = time.perf_counter()
        try:
            self._kokoro.create("hi.", voice=self._voice, speed=self._speed, lang="en-us")
            print(f"[tts warmup] {(time.perf_counter()-t0)*1000:.0f}ms")
        except Exception as e:  # noqa: BLE001
            print(f"[tts warmup] failed: {e}")

    def precache(self, text: str) -> bytes:
        """Synth `text` once and return WAV bytes. Caller stores the
        result and re-sends it whenever the same phrase is needed —
        zero TTS latency at the call site. Use for fixed greetings."""
        if not self._kokoro:
            return b""
        t0 = time.perf_counter()
        samples, sample_rate = self._kokoro.create(
            text, voice=self._voice, speed=self._speed, lang="en-us"
        )
        wav = _samples_to_wav(samples, sample_rate)
        print(f"[tts precache] {(time.perf_counter()-t0)*1000:.0f}ms "
              f"chars={len(text)} bytes={len(wav)}")
        return wav

    def synthesize(self, text: str) -> bytes:
        if not self._kokoro or not text:
            return b""
        t0 = time.perf_counter()
        samples, sample_rate = self._kokoro.create(
            text, voice=self._voice, speed=self._speed, lang="en-us"
        )
        wav = _samples_to_wav(samples, sample_rate)
        print(f"[tts one-shot] {(time.perf_counter()-t0)*1000:.0f}ms "
              f"chars={len(text)} bytes={len(wav)}")
        return wav

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """Yield WAV chunks as Kokoro produces them. First chunk lands
        before the full sentence is rendered, so playback can start
        earlier. Each chunk is a self-contained WAV the client decodes
        independently."""
        if not self._kokoro or not text:
            return
        t0 = time.perf_counter()
        t_prev = t0
        idx = 0
        async for samples, sample_rate in self._kokoro.create_stream(
            text, voice=self._voice, speed=self._speed, lang="en-us"
        ):
            wav = _samples_to_wav(samples, sample_rate)
            now = time.perf_counter()
            audio_secs = len(samples) / sample_rate
            print(f"[tts stream] chunk={idx} "
                  f"since_prev={(now-t_prev)*1000:.0f}ms "
                  f"since_start={(now-t0)*1000:.0f}ms "
                  f"audio={audio_secs*1000:.0f}ms bytes={len(wav)}")
            t_prev = now
            idx += 1
            yield wav
        print(f"[tts stream] done total={(time.perf_counter()-t0)*1000:.0f}ms "
              f"chunks={idx} chars={len(text)}")
