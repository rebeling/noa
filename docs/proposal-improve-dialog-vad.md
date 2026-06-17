# Proposal: Improve Dialog Turn-Taking & VAD

_Status: proposal (research + recommendation). No code changed by this document._

## 1. Problem

Conversational turns feel off. Two distinct causes — only one is VAD:

- **Filler on greetings (fixed).** Saying "Hi" made Noa stall-talk "let me look
  that up." Root cause was the spoken-filler gate, not VAD: with
  `COGNEE_SESSIONS=true`, `should_search` is true on every turn, and the filler
  was gated on `should_search`. Fixed by gating the filler on the
  question/recall heuristic instead — commit `7d53fdb`. The filler now stays
  quiet on greetings and short small-talk while retrieval still runs.

- **Turn detection is acoustic-only (this proposal).** The VAD is an amplitude
  threshold with no speech/noise discrimination, and end-of-turn is a fixed
  silence timeout with no notion of whether the speaker actually finished a
  thought. So it false-triggers on noise, clips mid-sentence on a pause, or
  makes the user wait after they've clearly finished.

## 2. Current implementation

Three small files under `app/speech_input/`, wired through a clean contract
boundary:

- **`_vad.py` — `AmplitudeVAD`.** `mean(|int16|) > 500`, mapped to a 0..1
  confidence. Microseconds per call, no model. No way to tell speech from a fan,
  a door, or typing. The comment notes the 0.4/0.2 thresholds were chosen to
  "match the prior Silero scale" — i.e. **Silero VAD was used before** and got
  swapped for this amplitude heuristic (likely for speed / fewer deps).

- **`_turn.py` — `TurnDetector`.** A pure silence counter:
  - `_REQUIRED_SILENCE_CHUNKS = 6` (~0.75s of trailing silence ends the turn)
  - `_SPEECH_START_CONFIDENCE = 0.4`
  - `_SILENCE_CONFIDENCE = 0.2`
  Timeout-only — it has no idea whether the utterance is grammatically/
  semantically complete. This is the part that makes turns "feel off."

- **`__init__.py` — `SpeechInputService.detect()`** runs
  `VAD.speech_confidence() → TurnDetector.on_confidence()` and returns
  `'start' | 'end' | None`. Partial transcripts already stream continuously via
  the orchestrator's `partial_loop`, so a semantic detector would have text
  available cheaply.

- **`app/contracts/providers.py`** defines a `VADProvider` ABC (VAD is already
  swappable). There is **no `TurnProvider` ABC** — `TurnDetector` is a bare
  concrete class. Adding one is the small structural change semantic turn
  detection needs.

## 3. AudioInteraction research

[xzf-thu/Audio-Interaction](https://github.com/xzf-thu/Audio-Interaction),
Apache-2.0.

- It is a **single end-to-end streaming audio LLM** (built on Qwen2.5-Omni),
  not a pipeline. It "keeps listening to incoming audio frames and decides for
  itself when to speak," defaulting to a `⟨Silent⟩` state and choosing
  `⟨Speak⟩`/`⟨Silent⟩` per chunk in one "always-on perceive–decide–respond
  loop." Recognition, translation, and dialogue are instructions inside that one
  model.
- **Verdict: not drop-in** for a Whisper + OpenAI/Claude + Kokoro pipeline —
  adopting it means replacing the whole stack with one model. Out of scope.
- **The transferable idea is the north star:** *comprehension-aware silence* —
  decide end-of-turn from semantic understanding, not acoustic silence. It also
  reports "asynchronous FIFO inference cuts first-frame latency 4.5×," an
  incremental-streaming insight this project already partly mirrors with
  sentence-level streaming TTS.

So AudioInteraction confirms the direction without giving us a component: make
turn-end **semantic**, keep the pipeline.

## 4. Adaptable options

| Option | What it fixes | Cost | Maps onto |
| --- | --- | --- | --- |
| **Tune thresholds** | Snappier/cleaner timeout | None (no deps) | Constants in `_turn.py` |
| **Silero VAD** | False triggers (noise vs speech) | New dep, lazy-load | New `VADProvider` impl, drop-in for `AmplitudeVAD` |
| **smart-turn** | The *feel* (semantic end-of-turn) | New dep + small contract change | New `TurnProvider` impl, consumes audio window + partial text |
| **LiveKit EOU** | Semantic EOU + barge-in during playback | New dep (ONNX model) | Alt to smart-turn |

Details:

- **Silero VAD** — neural speech/noise discrimination, MIT. Same
  `speech_confidence(chunk) -> float` signature as `AmplitudeVAD`, so it drops in
  behind the existing `VADProvider` with **zero orchestrator change**. The 0.4/
  0.2 thresholds already target the Silero scale. Fixes false triggers; does
  **not** fix the timeout feel.

- **smart-turn** ([pipecat-ai/smart-turn](https://github.com/pipecat-ai/smart-turn))
  — a Whisper-tiny-based **semantic end-of-utterance** model, ~12ms CPU
  inference, BSD-2. It waits on a trailing "What's the…" and fires immediately on
  a complete thought, using grammar/tone/pace rather than silence. This is the
  direct, practical realization of AudioInteraction's comprehension-aware
  silence for a pipeline.

- **LiveKit turn-detection / EOU** — multilingual ONNX EOU model, keeps turn
  detection active during playback for cleaner semantic barge-in. Alternative to
  smart-turn if multilingual EOU matters (this project runs en + de).

## 5. Recommended path (phased)

Each phase lands behind a contract boundary so the orchestrator never changes.

- **Phase 0 — done.** Filler-gate fix (`7d53fdb`). Removed the most visible
  "turn feels wrong" symptom that wasn't actually VAD.

- **Phase 1 — re-introduce Silero VAD.** Add a `SileroVAD(VADProvider)` in
  `app/speech_input/_vad.py` (or a new `_silero.py`), load it lazily like the ASR
  model, select it in `SpeechInputService.__init__` (env toggle, e.g. `NOA_VAD`).
  No change to `_turn.py`, contracts, or orchestrator. **Low risk, immediate
  quality** — kills false triggers from non-speech.

- **Phase 2 — semantic turn detection.** Add a `TurnProvider` ABC to
  `app/contracts/providers.py` mirroring `VADProvider`; make the existing
  `TurnDetector` implement it (no behavior change). Then add a
  `SmartTurnDetector(TurnProvider)` that consumes the recent audio window plus
  the latest partial transcript (already available from `partial_loop`) and
  returns end-of-turn from meaning, not the silence counter. Select via env
  toggle. **This is the real fix for "turns feel off."**

Rationale: **Silero answers "is this speech," smart-turn answers "are they
done."** That split is the modern turn-taking stack and matches AudioInteraction's
perceive–decide loop, decomposed for a pipeline.

## 6. Risks / notes

- **Model load:** both add a model. Keep them lazy (the ASR pattern in
  `SpeechInputService._get_asr()`) so boot stays fast.
- **CPU budget:** target is Apple Silicon; smart-turn is ~12ms/inference but runs
  per turn-end check — measure on-device before committing the cadence.
- **Barge-in must survive:** the orchestrator drops assistant audio on
  `SpeechStarted`. Any new VAD/turn detector must keep firing `'start'` promptly
  so barge-in still works.
- **Licenses:** Silero MIT, smart-turn BSD-2, LiveKit EOU permissive,
  AudioInteraction Apache-2.0 (referenced for ideas only, not vendored). All fit.
- **Toggle, don't replace:** gate each new provider behind an env var so the
  amplitude/timeout path stays as a zero-dep fallback.

## 7. Sources

- [xzf-thu/Audio-Interaction](https://github.com/xzf-thu/Audio-Interaction)
- [pipecat-ai/smart-turn](https://github.com/pipecat-ai/smart-turn)
- [LiveKit — Turn Detection for Voice Agents](https://livekit.com/blog/turn-detection-voice-agents-vad-endpointing-model-based-detection)
- [Agora — Making Voice AI Agents More Human with TEN VAD and Turn Detection](https://www.agora.io/en/blog/making-voice-ai-agents-more-human-with-ten-vad-and-turn-detection/)
