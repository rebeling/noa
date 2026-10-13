# Architecture

Noa is a chain of swappable parts. Each part implements an interface from
`app/contracts/` and talks to the others only through that package and the
event bus in `app/bus/`. The orchestrator wires one chain per WebSocket
session.

```
app/
├── contracts/      interfaces (VAD, ASR, LLM, TTS) and event types
├── bus/            in-process async pub/sub
├── speech_input/   Silero VAD → turn detector → Parakeet ASR
├── dialogue/       OpenAI or Anthropic, streamed, with persona prompt
├── synthesis/      Piper (or Kokoro) TTS, text cleanup for speech
├── orchestrator.py one session: routes audio and events between parts
├── _turn_text.py   greetings and LLM-stream segmenting
├── api/            FastAPI routes: voice page, voice WebSocket, login
├── core/           settings and JWT helpers
└── static/, templates/   the orb UI
```

## One turn

1. The browser captures 16 kHz mono PCM in 128 ms frames and sends them over
   the WebSocket.
2. Silero scores each frame. Speech above 0.5 starts a turn; 0.5 s of audio
   below 0.35 ends it.
3. While the user speaks, a background loop transcribes the last 6 s of
   audio every 250 ms and streams partial text to the UI. On long turns the
   window slides and older text is frozen so nothing is transcribed twice.
4. At turn end the final transcript is taken from the last partial when it
   is fresh and covers the whole turn, otherwise the full turn is decoded
   once more.
5. The transcript goes to the LLM as a stream. Text is cut into segments:
   the first at the first clause boundary after 12 characters, then at
   sentence ends. Each segment is cleaned for speech (markdown, URLs,
   length cap) and sent to TTS while the LLM is still generating.
6. Each TTS chunk is a self-contained WAV, played by the browser as it
   arrives.

## Barge-in

The browser watches microphone level while the assistant is processing or
speaking. Sustained voice for 900 ms sends a `barge_in` message. The server
cancels the reply task, tells the client to drop queued audio, and returns
to listening. The threshold ignores short backchannels like "ok" or "hm".

## WebSocket protocol

Client to server: binary frames are PCM audio. Text frames are JSON:

| type | fields | effect |
| --- | --- | --- |
| `set_language` | `language` | switch ASR, LLM and TTS language mid-session |
| `barge_in` | | cancel the current reply |
| `text_input` | `text` | run a turn from typed text, skipping VAD and ASR |

Server to client: binary frames are WAV audio chunks. Text frames:

| type | fields | meaning |
| --- | --- | --- |
| `status` | `text` | `Listening...`, `Processing...`, `Speaking...`, `Waiting...` |
| `user_transcript_chunk` | `committed`, `tail` | live partial transcript |
| `transcript` | `text`, `provisional` | the user's finished turn |
| `response_chunk` | `text` | one spoken segment of the reply |
| `response` | `text` | a complete reply (greeting, stub, error) |
| `stop_audio` | | drop queued playback |

## Startup and latency

- The English TTS loads and warms at boot and is shared across sessions.
- Parakeet loads on the first transcription of a session.
- The LLM connection is opened while the greeting plays.
- Heavy imports (`parakeet_mlx`, `piper`, `kokoro_onnx`, `openai`,
  `anthropic`) never run at module import time. `tests/` checks this.

Typical numbers on an M-series Mac: first partial transcript within 300 ms
of speech, first audio 1 to 1.5 s after the user stops talking, most of it
spent waiting for the LLM's first sentence.

## Reply modes

`NOA_REPLY_MODE` selects how a finished turn is answered:

- `real` runs the LLM and TTS.
- `echo` waits 1 to 2.5 s, then speaks the user's words back. Exercises TTS
  and barge-in without an API key.
- `fake` sends timed status changes and the text `ok`. Exercises the UI and
  barge-in with no models at all.

## Auth

The voice page mints a short-lived JWT for the browser and the WebSocket
validates it. The token carries a `role` claim (`admin` or `customer`) that
nothing checks today; it exists so a future layer can gate writes. There is
also a password login endpoint for one bootstrap admin, configured through
`BOOTSTRAP_ADMIN_USERNAME` and `BOOTSTRAP_ADMIN_PASSWORD_HASH`.

## Not done yet

- Memory. A knowledge-graph layer was tried and removed because retrieval
  took seconds. Replies have no memory beyond the session.
- Semantic end-of-turn. Turn end is time-based; a model that judges
  whether the thought is complete would cut false endings.
- Faster first sentence from the LLM. It is the largest share of the delay.
