# TTS Pipeline — Reply Synthesis (Fake or Real)

After the final transcript reaches the screen the orchestrator runs a
reply phase. The reply phase has **two interchangeable implementations**
selected at boot by the `NOA_REPLY_MODE` environment variable. Both
share the same status protocol and the same barge-in cancellation, so
the client orb behaves identically and you can flip modes without
touching the UI.

**Source files:**
- `app/orchestrator.py` — `_delayed_reply`, `_fake_reply`, `_real_reply`
- `app/dialogue/__init__.py`, `app/dialogue/_llm.py` — LLM call
- `app/synthesis/__init__.py`, `app/synthesis/_kokoro.py` — Kokoro TTS
- `Makefile` — `start` / `start-real` / `start-http`

## Modes

| mode | env | what runs | when to use |
|------|-----|-----------|-------------|
| `fake` (default) | `NOA_REPLY_MODE=fake` | 2s `Processing...` + 3s `Speaking...` timers, stub `"ok"` text, **no LLM, no TTS, no audio bytes** | offline debug: barge-in, orb states, latency tuning, no API cost |
| `real` | `NOA_REPLY_MODE=real` | `dialogue.respond()` (OpenAI) → response text → status=Speaking → `synthesis.synthesize()` (Kokoro) on a worker thread → audio bytes → status=Waiting | production-shape behaviour with the real LLM + TTS |

Both modes follow the same status protocol so the client orb (the
plasma blob in `voice.html`) behaves identically:

```
status=Processing  -> orb -> 'processing' (purple pulse)
status=Speaking    -> orb -> 'speaking'   (orange outward)
status=Waiting     -> orb -> 'listening'  (green inward)
```

## Switching modes

Makefile shortcuts:

```bash
make start       # HTTPS, fake mode (debug timers, no LLM/TTS)
make start-real  # HTTPS, real mode (OpenAI + Kokoro)
make start-http  # plain HTTP, fake mode (localhost only)
```

Or set the env var directly:

```bash
NOA_REPLY_MODE=real uv run uvicorn app.main:app --reload \
  --ssl-keyfile certs/dev-key.pem --ssl-certfile certs/dev-cert.pem
```

The active mode is printed on every new session:

```
session: reply_mode=fake language=en
```

## Fake mode — `_fake_reply`

```python
status=Processing...   # 0.0s
sleep(_FAKE_PROCESSING_SECS)   # default 2.0s
response="ok"
status=Speaking...     # 2.0s
sleep(_FAKE_SPEAKING_SECS)     # default 3.0s
status=Waiting...      # 5.0s, done
```

No LLM call. No TTS call. No audio bytes sent. The 2s + 3s split exists
so both `processing` and `speaking` are long enough to barge into by
hand.

**Why keep it.** Heavy models (OpenAI roundtrip, Kokoro first-load,
faster-whisper) make every iteration slow and add API cost. The fake
path is the offline rig for:
- Barge-in plumbing (does it cancel cleanly in both phases?)
- Orb state transitions (do the colours change at the right time?)
- VAD / endpointing latency (without LLM noise in the timing log)
- UI work that depends on `status` / `response` / `stop_audio`

It is meant to stay — not a placeholder waiting to be deleted.

## Real mode — `_real_reply`

```python
status=Processing...
reply = await dialogue.respond(text)        # OpenAI roundtrip
response=reply                              # text shown immediately
status=Speaking...
audio = await asyncio.to_thread(            # off the event loop
    synthesis.synthesize, reply)
if audio: send_bytes(audio)                 # WAV bytes -> client WebAudio
status=Waiting...
```

`DialogueService.respond()` calls OpenAI (`gpt-4o-mini`, persona "Noa").
`SynthesisService.synthesize()` calls Kokoro to render the reply to WAV
audio in one shot — no streaming. Both heavy deps load lazily on the
first call of the session.

**First-turn cost.** The first real-mode reply loads `openai`,
`kokoro_onnx`, and the Kokoro voice models. Expect a slow first turn
and a fast second turn.

## The wrapper — `_delayed_reply`

`on_turn_ended` always spawns the same wrapper task; the wrapper picks
fake or real and owns the cancellation cleanup, so both modes look the
same to the rest of the system:

```python
async def _delayed_reply(text: str) -> None:
    try:
        if _REPLY_MODE == "real":
            await _real_reply(text)
        else:
            await _fake_reply(text)
    except asyncio.CancelledError:
        # Barge-in path — drop assistant audio, return to listening.
        await _safe_send_text(websocket, json.dumps({"type": "stop_audio"}))
        await _safe_send_text(websocket, json.dumps(
            {"type": "status", "text": "Listening..."}))
        raise
```

The task handle is kept in `pending_reply` on the session, so the
receive loop's `barge_in` handler can cancel it.

## Barge-in interaction

When the user speaks during `processing` or `speaking`, the client sends
`{"type":"barge_in"}` (see `docs/stt-pipeline.md` for the trigger
details). The orchestrator cancels `pending_reply`:

```python
elif ctype == "barge_in":
    if pending_reply is not None and not pending_reply.done():
        pending_reply.cancel()
        pending_reply = None
        print("barge_in: cancelled pending reply")
```

The CancelledError handler in `_delayed_reply` sends `stop_audio`
(client clears its WebAudio queue) and `status=Listening`. Same path in
both modes.

**Caveat (real mode):** a barge-in fired while Kokoro is mid-synthesis
cannot interrupt the worker thread — `asyncio.to_thread` is
uninterruptible. The synthesis finishes internally, but the `await`
never resumes, so no audio bytes are sent. The client still receives
`stop_audio` + `status=Listening` from the CancelledError handler.
Acceptable; not perfect.

## Server → client messages emitted by the reply phase

| type | fake | real | meaning |
|------|------|------|---------|
| `status` | ✓ | ✓ | `Processing...` / `Speaking...` / `Waiting...` / `Listening...` |
| `response` | `"ok"` | LLM reply text | assistant reply, rendered as a chat bubble |
| `stop_audio` | on cancel | on cancel | client clears playback queue |
| binary frame (WAV) | — | ✓ | TTS audio for browser WebAudio playback |

## Performance Conclusion
Reducing first‑chunk latency in a voice agent requires more than just a fast TTS model. It demands an end‑to‑end streaming architecture that overlaps ASR, LLM, TTS and playback. For open‑source, local deployment in English, **Piper and Kokoro** currently provide the fastest first‑chunk performance, delivering audio in under 100–300 ms on commodity hardware.

Whichever model you choose, **stream the LLM output sentence by sentence** and **pre-load the model** to ensure your agent responds as quickly as a human.

## Tuning knobs

| constant | file | effect |
|----------|------|--------|
| `NOA_REPLY_MODE` | env | `fake` (debug timers) vs `real` (OpenAI + Kokoro) |
| `_FAKE_PROCESSING_SECS` | `orchestrator.py` | fake-mode "thinking" duration (default 2.0s) |
| `_FAKE_SPEAKING_SECS` | `orchestrator.py` | fake-mode "speaking" duration (default 3.0s) |
| Kokoro model paths | `_kokoro.py` | swap voice / model file |
| OpenAI model name | `_llm.py` | accuracy vs latency vs cost |
