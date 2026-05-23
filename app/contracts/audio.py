"""Audio data types shared across pipeline parts."""

from dataclasses import dataclass

# Pipeline-wide audio format. PCM signed 16-bit, mono, 16 kHz —
# matches faster-whisper input and the browser capture rate.
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # bytes per sample (int16)
CHANNELS = 1


@dataclass(frozen=True)
class AudioChunk:
    """A slice of raw PCM audio moving through the pipeline.

    `data` is signed 16-bit little-endian PCM at SAMPLE_RATE, mono.
    """

    data: bytes

    @property
    def duration_secs(self) -> float:
        return len(self.data) / (SAMPLE_RATE * SAMPLE_WIDTH * CHANNELS)
