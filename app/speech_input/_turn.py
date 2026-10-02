"""Turn detection — internal to speech_input.

Tracks speech-start / end-of-turn from a stream of VAD confidences.
End-of-turn fires after `end_silence_secs` of *audio time* below the
silence threshold, so the result does not depend on how big the client's
audio frames are.
"""

# Seconds of trailing silence that end a turn. Lower = Noa replies sooner
# after you stop; too low clips natural mid-sentence pauses.
_END_OF_TURN_SILENCE_SECS = 0.5


class TurnDetector:
    """Feed it VAD confidences + the audio duration they cover; it reports
    state transitions."""

    def __init__(
        self,
        start_confidence: float,
        silence_confidence: float,
        end_silence_secs: float = _END_OF_TURN_SILENCE_SECS,
    ) -> None:
        self._start_confidence = start_confidence
        self._silence_confidence = silence_confidence
        self._end_silence_secs = end_silence_secs
        self._is_speaking = False
        self._silence_secs = 0.0

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    def on_confidence(self, confidence: float, audio_secs: float) -> str | None:
        """Update state with a new VAD confidence covering `audio_secs`.

        Returns 'start' on speech onset, 'end' on end-of-turn,
        None when nothing changed.
        """
        if not self._is_speaking:
            if confidence > self._start_confidence:
                self._is_speaking = True
                self._silence_secs = 0.0
                return "start"
            return None

        if confidence < self._silence_confidence:
            self._silence_secs += audio_secs
        else:
            self._silence_secs = 0.0

        if self._silence_secs >= self._end_silence_secs:
            self._is_speaking = False
            self._silence_secs = 0.0
            return "end"
        return None
