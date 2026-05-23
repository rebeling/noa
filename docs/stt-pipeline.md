# STT Pipeline — Speech-to-Text

How Noa turns a live microphone stream into text. Covers the wire format,
voice-activity detection, turn-taking, and the partial/final transcription
split. Source files: `app/services/speech.py`, `app/services/orchestrator.py`,
`app/templates/voice.html`.

## Overview

```
browser mic ──PCM int16──▶ WebSocket ──▶ orchestrator.run_session
                                              │
                                    ┌─────────┴─────────┐
                                    │                   │
                              amplitude VAD       partial_loop (task)
                              (every chunk)       (every 400ms)
                                    │                   │
                              turn-taking         transcribe(partial)
                                    │                   │
                              speech END          user_transcript_chunk
                                    │                   ▼
                              transcribe(final) ──▶ transcript + response
```

One WebSocket session = one `run_session` coroutine. The receive loop only
buffers audio and runs cheap VAD; all transcription happens off the loop.

## Wire format

- **Encoding:** raw PCM, signed 16-bit, mono, **16 kHz**.
- **Rate:** 32000 bytes/sec (`16000 * 2`).
- Browser captures via `ScriptProcessor` (4096-sample frames), converts
  float32 `[-1,1]` → int16, sends each frame as a binary WebSocket message.
- Server appends every message to `audio_buffer` (a `bytearray` holding the
  current turn's audio).

## Voice Activity Detection (VAD)

VAD answers one question per chunk: *is someone speaking right now?*

Noa uses **amplitude VAD** - `SpeechService.is_speech()` in `speech.py`:

```python
mean_amp = float(np.abs(audio_int16.astype(np.int32)).mean())
return min(1.0, mean_amp / (VAD_AMP_THRESHOLD / 0.4))
```

Mean absolute sample value, normalized so the `VAD_AMP_THRESHOLD` (500) maps
to ~0.4. Pure arithmetic — microseconds per call, no neural net.

**Why not Silero.** Earlier builds used the Silero-VAD neural model. It ran a
torch forward pass on *every* audio chunk (~12×/sec for the whole time the
mic was open). That continuous inference was the dominant pipeline cost —
it competed with transcription for CPU and was the real source of perceived
latency. Amplitude VAD removed it. The trade-off: amplitude VAD is fooled by
loud background noise where Silero is not. Acceptable for now; revisit if
noisy environments become a target. Whisper still runs its own internal
`vad_filter` during the final transcribe as a second line of defense.

Because VAD is now cheap, it runs **inline** in the receive loop — no
`asyncio.to_thread` hop.

## Turn-taking

The receive loop tracks two states with the VAD confidence:

| state | trigger | action |
|-------|---------|--------|
| **start of speech** | `confidence > 0.4` while idle | mark `is_speaking`, start `partial_loop`, send `Listening...`, send `stop_audio` (barge-in: cut any playback) |
| **silence** | `confidence < 0.2` while speaking | increment `silence_counter` |
| **end of speech** | `silence_counter >= 8` (~1s) | stop `partial_loop`, run final transcribe |

`REQUIRED_SILENCE_CHUNKS = 8` ≈ 1 second of trailing silence before a turn is
considered complete. Raise it if short utterances end the turn too early;
lower it for snappier turn-taking at the risk of cutting people off.

## Transcription: partial vs final

Transcription is **`faster-whisper`** (`WhisperModel`), model `base`,
`device="cpu"`, `compute_type="int8"`. Greedy decoding (`beam_size=1`),
`condition_on_previous_text=False` — both keep latency bounded.

There are two transcription paths, and keeping them off the receive loop is
the key design point.

### Partial (live)

`partial_loop()` is a background `asyncio.Task` started at speech-start:

1. Every `PARTIAL_POLL_SECS` (0.4s), snapshot the buffer.
2. Skip if under 8000 bytes (~0.25s audio — too little to transcribe).
3. `transcribe(snapshot, partial=True)` via `asyncio.to_thread` — the CPU
   work runs on a worker thread, the event loop stays free.
4. Send a `user_transcript_chunk` message **only if the transcript grew**
   (`len(txt) > len(last_partial)`) — prevents flicker from re-decodes.

The receive loop never `await`s transcription, so incoming mic bytes never
back up behind a decode.

### Final

On speech-end:

1. Cancel `partial_loop` so the final transcribe isn't queued behind an
   in-flight partial. (A `to_thread` call already running can't be
   cancelled, so at worst the final waits one ~0.4s partial pass.)
2. `transcribe(full_buffer, partial=False)` on the whole utterance.
3. Send `transcript` (the committed text), then the response.
4. Clear the buffer and reset state for the next turn.

Final transcribes the **entire** utterance, not just a tail — partials are
throwaway previews; the final pass is authoritative.

## WebSocket message types (server → client)

| type | meaning |
|------|---------|
| `status` | UI state line: `Listening...` / `Processing...` / `Waiting...` |
| `stop_audio` | barge-in — client clears its playback queue |
| `user_transcript_chunk` | live partial transcript (`committed` + `tail`); rendered dimmed |
| `transcript` | final user transcript; solidifies the live bubble |
| `response` | assistant reply (currently stubbed `"ok"` — see below) |

## Current limitations

- **Response stage is stubbed.** On final transcript the server replies a
  flat `"ok"`. RAG / LLM / TTS are disabled to isolate ASR latency — see
  `orchestrator.py` `run_session`. Re-enable when STT latency is settled.
- **One model, one CPU.** Partial and final transcription share a single
  `WhisperModel`. Concurrent passes serialize. The partial-cancel-on-end
  logic keeps the final pass first in line.
- `transcribe()` prints a timing line — `>>> transcribe: X.XXs for Y.Ys
  audio (RTF Z.ZZ)` — for latency measurement. RTF < 1.0 means faster than
  real time.

## Tuning knobs

| constant | file | effect |
|----------|------|--------|
| `VAD_AMP_THRESHOLD` | `speech.py` | higher = needs louder speech to register |
| `REQUIRED_SILENCE_CHUNKS` | `orchestrator.py` | trailing-silence length to end a turn |
| `PARTIAL_POLL_SECS` | `orchestrator.py` | how often live partials refresh |
| Whisper model name | `speech.py` | `tiny` faster / `small`+ more accurate |
