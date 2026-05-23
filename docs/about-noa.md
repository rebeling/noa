# About Noa

**Noa** is a voice-driven dialogue assistant. You speak to it through a
browser; it listens, thinks, and talks back — with natural turn-taking.

This page describes what Noa *appears* to do during a conversation: its
visible states, and how it keeps listening even while it is busy.
Architecture source of truth is
[`system-design.md`](../system-design.md); the speech path is detailed in
[`stt-pipeline.md`](./stt-pipeline.md).

## Noa's states

A conversation moves Noa through four visible states. They drive the
on-screen blob (the "aura") and tell the user what Noa is doing right now.

| State | Sub-label | When | Aura |
|-------|-----------|------|------|
| **idle** | "asleep" | Mic off, or no active turn | Slow soft wobble, cyan glow, halo still |
| **listening** | — | Mic on, speech detected — Noa is hearing you | Tight quick wobble, green glow, halo pulls inward |
| **processing** | — | Turn ended — ASR + LLM running | Gentle fast pulse, violet glow, halo pulses |
| **speaking** | — | Reply synthesized — TTS audio streaming out | Big loose waves, orange glow, halo radiates outward |

## State cycle

```
   idle ─speech─▶ listening ─silence─▶ (holding) ─hold done─▶ processing ─reply─▶ speaking
           ▲          ▲                    │                     │                  │
           │          │                    │                     │                  │
           │          └──── barge-in ──────┴─────────────────────┴──────────────────┘
           │                 (user speaks while Noa is busy)
           └──────────────── session end / no turn ───────────────────────────────────
```

A full conversational turn is `listening → (holding) → processing →
speaking → listening`. `holding` is an internal state — the user sees it
as `processing`. The loop repeats until the session ends.

## Capabilities in dialogue

### Turn-end hold — adaptive thinking delay

When you stop talking, Noa does not pounce on the reply instantly. It
first **holds** for a short beat to decide "is the user really done?" —
this is the job of a turn detector. The length of that hold adapts to
how much you said:

| You said | Hold before processing | Why |
|----------|------------------------|-----|
| `"hi"` (1 word) | ~1.5s | A one-word utterance is an ambiguous turn end — you may still be forming the sentence, so Noa waits. |
| A full sentence (7+ words) | ~0.2s | A long sentence is a clear, finished thought — Noa commits almost immediately. |

So **the longer you speak, the sooner Noa starts answering.** Short
fragments get a longer grace period; complete sentences get a near-instant
start.

This hold happens in an internal `holding` state; the user simply sees
`processing`, since the hold is part of the perceived answer latency.
After the hold, Noa enters `processing` proper (currently a simulated
"thinking" delay standing in for the real LLM, also slightly shorter for
longer input).

Both the hold and the simulated thinking are fully interruptible — see
barge-in below.

### Always listening

Noa's microphone loop runs in **every** state — including `processing`
and `speaking`. The states `processing` and `speaking` are not "deaf":
they simply have a background task attached (ASR/LLM, or TTS playback)
that can be cancelled. The audio stream is never stopped, and voice
detection never pauses.

This is what makes the assistant feel responsive instead of walkie-talkie:
you do not have to wait for Noa to finish before you can speak.

### Barge-in — interrupting Noa

Because Noa keeps listening while busy, two interruptions are possible:

- **Speaking → listening.** Noa is talking; you start to speak. Noa stops
  its own audio immediately, drops the rest of the reply, and switches
  back to `listening`. This is classic barge-in.
- **Processing → listening.** Noa is still thinking — either in the
  turn-end `holding` beat or the `processing` delay — and you add to or
  correct what you said. Noa abandons the in-flight reply and goes
  straight back to `listening` — *"suddenly listening"* mid-think.

In both cases the audio you spoke during the interruption is already
captured (the mic loop never stopped), so nothing is lost.

### Hearing its own voice

A real risk: Noa's spoken reply plays through the speaker, the microphone
picks it up, and Noa mistakes its **own voice** for a user barge-in —
interrupting itself in a loop. Noa guards against this two ways:

1. **Echo cancellation (client).** The browser microphone is opened with
   `echoCancellation` on, so Noa's playback is subtracted from the mic
   signal before voice detection ever sees it.
2. **Stricter barge-in while speaking (server).** During `speaking`, an
   interrupt requires a higher loudness threshold *and* several
   consecutive speech chunks (a debounce), so any echo that survives
   step 1 does not trigger a false interrupt. During `processing` —
   when Noa emits no audio — the normal, faster threshold is used.

## Where state lives

State is tracked on both sides:

- **Server** ([`app/services/orchestrator.py`](../app/services/orchestrator.py))
  — holds the authoritative state machine (`State` enum:
  `idle | listening | holding | processing | speaking`; `holding` is
  reported to the client as `processing`). All changes go through a
  single `transition()` choke point that validates the move against a
  legal-transition table and pushes a `{"type": "status", "text": ...}`
  message over the WebSocket. The non-blocking receive loop owns the
  socket; ASR/LLM/TTS run in a separate cancellable task.
- **Client** ([`app/templates/voice.html`](../app/templates/voice.html)) —
  mirrors server state from `status` messages to drive the aura, and also
  reacts to local mic and audio-playback events.
