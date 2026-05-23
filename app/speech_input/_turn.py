"""Turn detection — internal to speech_input.

Tracks speech-start / end-of-turn from a stream of VAD confidences,
using a silence counter. Logic lifted from the prior orchestrator
session loop so behavior is unchanged.
"""

# ~1s of end-of-turn silence (8 chunks of ~4000 bytes at 16kHz int16).
_REQUIRED_SILENCE_CHUNKS = 8
_SPEECH_START_CONFIDENCE = 0.4
_SILENCE_CONFIDENCE = 0.2


class TurnDetector:
    """Feed it VAD confidences; it reports state transitions."""

    def __init__(self) -> None:
        self._is_speaking = False
        self._silence_counter = 0

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    def on_confidence(self, confidence: float) -> str | None:
        """Update state with a new VAD confidence.

        Returns 'start' on speech onset, 'end' on end-of-turn,
        None when nothing changed.
        """
        if not self._is_speaking:
            if confidence > _SPEECH_START_CONFIDENCE:
                self._is_speaking = True
                self._silence_counter = 0
                return "start"
            return None

        if confidence < _SILENCE_CONFIDENCE:
            self._silence_counter += 1
        else:
            self._silence_counter = 0

        if self._silence_counter >= _REQUIRED_SILENCE_CHUNKS:
            self._is_speaking = False
            self._silence_counter = 0
            return "end"
        return None
