"""Audio data types shared across pipeline parts."""

from dataclasses import dataclass

# Pipeline-wide audio format: PCM signed 16-bit, mono, 16 kHz. Matches the
# browser capture rate and what Silero and Parakeet expect.
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2  # bytes per sample (int16)
CHANNELS = 1


@dataclass(frozen=True)
class AudioChunk:
    """A slice of raw PCM audio: signed 16-bit little-endian, mono, 16 kHz."""

    data: bytes
