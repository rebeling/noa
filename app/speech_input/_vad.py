"""Amplitude-based VAD — internal to speech_input.

Mean absolute int16 sample value, normalized 0..1. No neural model:
microseconds per call. Scale tuned so callers compare against
0.4 (speech start) / 0.2 (silence), matching the prior Silero scale.
"""

import numpy as np

from app.contracts import AudioChunk, VADProvider

# Mean |int16| above this counts as voice.
_VAD_AMP_THRESHOLD = 500


class AmplitudeVAD(VADProvider):
    def speech_confidence(self, chunk: AudioChunk) -> float:
        audio_int16 = np.frombuffer(chunk.data, dtype=np.int16)
        if audio_int16.size == 0:
            return 0.0
        mean_amp = float(np.abs(audio_int16.astype(np.int32)).mean())
        # map threshold (500) -> ~0.4 so existing comparisons still hold
        return min(1.0, mean_amp / (_VAD_AMP_THRESHOLD / 0.4))
