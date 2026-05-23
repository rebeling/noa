"""Piper TTS — fast CPU-only ONNX TTS.

Install: `uv add piper-tts` (or `piper-onnx`). Models are downloaded
separately from https://github.com/rhasspy/piper/releases — voice
files are <60MB each, much smaller than Kokoro.

Streams audio per phrase. On typical CPU hardware Piper produces
first audio in 200–500ms for short replies, vs Kokoro's 2–6s.
"""

import io
import os
import time
import wave
from collections.abc import AsyncGenerator
from pathlib import Path

from app.contracts import TTSProvider


# Voice file picked via NOA_PIPER_VOICE env var; default to Jenny (GB).
# Drop any compatible Piper voice .onnx + .onnx.json pair into voices/
# and reference by basename or relative path.
_DEFAULT_MODEL = os.environ.get(
    "NOA_PIPER_VOICE", "voices/en_GB-jenny_dioco-medium.onnx"
)


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    """Wrap raw int16 PCM bytes in a WAV container."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buffer.getvalue()


class PiperTTS(TTSProvider):
    def __init__(self, model_path: str = _DEFAULT_MODEL) -> None:
        self._model_path = model_path
        self._piper = None
        self._sample_rate = 22050  # default; replaced after load
        t0 = time.perf_counter()
        try:
            # Piper's Python binding API varies by version. Try the
            # most common shape: `from piper import PiperVoice`.
            from piper.voice import PiperVoice
            if not Path(model_path).exists():
                print(f"Piper model missing: {model_path}. "
                      f"Download from https://github.com/rhasspy/piper/releases")
                return
            self._piper = PiperVoice.load(model_path)
            self._sample_rate = self._piper.config.sample_rate
            print(f"[tts init] Piper loaded in {(time.perf_counter()-t0)*1000:.0f}ms "
                  f"model={model_path} sr={self._sample_rate}")
        except ImportError:
            print("Piper not installed. Run: uv add piper-tts")
        except Exception as e:  # noqa: BLE001
            print(f"Piper init failed: {e}")

    def is_ready(self) -> bool:
        return self._piper is not None

    def warmup(self) -> None:
        if not self._piper:
            return
        t0 = time.perf_counter()
        try:
            list(self._piper.synthesize("hi."))
            print(f"[tts warmup] {(time.perf_counter()-t0)*1000:.0f}ms")
        except Exception as e:  # noqa: BLE001
            print(f"[tts warmup] failed: {e}")

    def _synth_wav(self, text: str) -> bytes:
        if not self._piper or not text:
            return b""
        # New piper API: synthesize() yields AudioChunk objects with
        # raw int16 PCM bytes. Concatenate and wrap in one WAV.
        pcm = b"".join(c.audio_int16_bytes for c in self._piper.synthesize(text))
        return _pcm_to_wav(pcm, self._sample_rate)

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
        """Stream WAV chunks. Piper yields one AudioChunk per sentence
        internally; we wrap each as a self-contained WAV so the client
        can start playback on the first sentence."""
        if not self._piper or not text:
            return
        t0 = time.perf_counter()
        t_prev = t0
        idx = 0
        for ac in self._piper.synthesize(text):
            wav = _pcm_to_wav(ac.audio_int16_bytes, self._sample_rate)
            now = time.perf_counter()
            audio_secs = len(ac.audio_int16_bytes) / 2 / self._sample_rate
            print(f"[tts stream] piper chunk={idx} "
                  f"since_prev={(now-t_prev)*1000:.0f}ms "
                  f"since_start={(now-t0)*1000:.0f}ms "
                  f"audio={audio_secs*1000:.0f}ms bytes={len(wav)}")
            t_prev = now
            idx += 1
            yield wav
        print(f"[tts stream] done total={int((time.perf_counter()-t0)*1000)}ms "
              f"chunks={idx} chars={len(text)}")
