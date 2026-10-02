"""Silero VAD — internal to speech_input.

Neural speech/noise discrimination via pysilero-vad (MIT; ggml backend, no
torch). The model is stateful (RNN) and consumes fixed 512-sample frames
(1024 bytes of int16 @ 16 kHz), so callers must feed it every byte in
order: this class buffers whatever it is given and runs each complete
frame, returning the max speech probability over the frames processed in
this call (or the previous value if no full frame arrived).
"""

from app.contracts import AudioChunk, VADProvider


class SileroVAD(VADProvider):
    def __init__(self) -> None:
        from pysilero_vad import SileroVoiceActivityDetector

        self._vad = SileroVoiceActivityDetector()
        self._frame_bytes = SileroVoiceActivityDetector.chunk_bytes()  # 1024
        self._pending = bytearray()
        self._last = 0.0

    def speech_confidence(self, chunk: AudioChunk) -> float:
        self._pending.extend(chunk.data)
        best: float | None = None
        while len(self._pending) >= self._frame_bytes:
            frame = bytes(self._pending[: self._frame_bytes])
            del self._pending[: self._frame_bytes]
            prob = float(self._vad.process_chunk(frame))
            best = prob if best is None else max(best, prob)
        if best is not None:
            self._last = best
        return self._last
