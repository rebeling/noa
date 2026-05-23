# Noa - Documentation

**Noa** is a **voice-driven dialogue
assistant**. It ingests documents into a knowledge base memory and holds
low-latency spoken conversations with natural turn-taking. The memory uses
cognee and we wanne figure out if an admin can update the facts in the memory.
User then get up to date informations.

This is the docs index. Architecture source of truth is
[`system-design.md`](../system-design.md); per-layer work is tracked in
[`docs/superpowers/tasks/`](./superpowers/tasks).

## What it does

1. A user speaks to Noa through a browser. Audio streams to the server.
2. Noa detects speech, transcribes it, and shows text live as you talk.
3. The dialogue manager retrieves relevant facts from the user's private
   knowledge graph and an LLM generates a short spoken reply.
4. The reply is synthesized to speech and streamed back — interruptible.
5. Separately, admins ingest documents; they are PII-redacted before
   entering the knowledge graph.

## Pipeline

A chain of swappable services — any one (ASR, TTS, LLM) can be replaced
without touching the others.

```
                    ┌─────────────────────────────────────────┐
  browser  ──audio──▶  Client & Transport  (WebSocket, JWT)    │
                    └───────────────────┬─────────────────────┘
                                        ▼
                    ┌─────────────────────────────────────────┐
                    │  Speech Input    VAD → turn → ASR        │
                    │                  (partial + final text) │
                    └───────────────────┬─────────────────────┘
                                        ▼
                    ┌─────────────────────────────────────────┐
                    │  Dialogue Mgmt   orchestrator + LLM      │
                    └─────────┬───────────────────┬───────────┘
                              ▼                   ▼
              ┌───────────────────────┐  ┌──────────────────────┐
              │ Knowledge (Cognee)    │  │ Response Synthesis    │
              │ graph + vector store  │  │ post-process → TTS    │
              └───────────────────────┘  └──────────┬───────────┘
                                                    ▼
                                          audio streamed to browser

  Ingestion (admin): upload → PII/PHI redaction → Cognee
```

## The five layers

| # | Layer | What it does | Tech |
|---|-------|--------------|------|
| 1 | **Client & Transport** | Audio capture, streaming, TLS, JWT, role routing | WebSocket, FastAPI gateway, HTMX UI |
| 2 | **Speech Input** | Voice detection, turn-taking, transcription | amplitude VAD, faster-whisper |
| 3 | **Dialogue Management** | Session state, intent, response generation | orchestrator, OpenAI LLM |
| 4 | **Knowledge** | Per-user graph/vector store, retrieval | Cognee |
| 5 | **Response Synthesis** | Text post-process, speech output | Kokoro TTS |

## Deep-dive docs

- **[About Noa](./about-noa.md)** — Noa's conversation states (idle,
  listening, processing, speaking), the always-listening / barge-in
  behavior, the adaptive turn-end hold, and where state lives.
- **[STT Pipeline](./stt-pipeline.md)** — speech-to-text in detail: wire
  format, amplitude VAD, turn-taking, partial vs final transcription.
- **[TTS / Reply Phase](./tts.md)** — the `NOA_REPLY_MODE` fake-vs-real
  switch, the two-phase `Processing` + `Speaking` window, and the
  barge-in cancellation path shared by both modes.
- **[Libraries by Area](./libraries.md)** — every third-party library
  Noa uses, grouped by area (frontend, backend, ASR, TTS, processing,
  knowledge, redaction, auth).
- *(more layer docs to follow)*

## Non-negotiable conventions

These are hard rules, enforced in code — not optional features.

- **Data isolation.** Every Cognee read and write carries `user_id` +
  `dataset_id`. Storage is per-tenant: `.cognee_system/databases/<user_uuid>/
  <dataset_uuid>`. No path may cross tenants. Cognee runs with
  `ENABLE_BACKEND_ACCESS_CONTROL=true`.
- **PII/PHI redaction is mandatory.** No document reaches Cognee without
  passing the redaction layer (Presidio/Phileas) first. No bypass paths.
- **RBAC at the gateway.** Admins ingest and manage datasets; Customers
  query only. Enforced at the gateway, not just the UI.
- **Model licenses matter.** Any ASR/TTS model added must have a license
  fitting the intended use.

## Current status

Early stage — design is ahead of implementation. Where each layer stands:

| Layer | State |
|-------|-------|
| Client & Transport | JWT gateway + HTMX UI done; WebRTC signaling pending |
| Speech Input | **Working** — amplitude VAD + faster-whisper, live partials + final. See [STT doc](./stt-pipeline.md) |
| Dialogue Management | Orchestrator wired; reply phase selectable via `NOA_REPLY_MODE` (fake default / real). See [TTS doc](./tts.md) |
| Knowledge | Ingestion path + Presidio redaction done; multi-tenant isolation audit in progress |
| Response Synthesis | Kokoro TTS integrated; active in real mode, skipped in fake mode |

**Known gaps:** the response stage (RAG → LLM → TTS) is intentionally turned
off while STT latency is being tuned — it must be re-enabled. Cognee calls do
not yet pass `user_id` (data-isolation gap). See per-layer files in
[`docs/superpowers/tasks/`](./superpowers/tasks) for checklists.

## Running it

Project uses `uv` (not pip/venv). Requires Python ≥ 3.14.

```bash
uv sync                 # install dependencies
uv run main.py          # run the app
uv run pytest           # run tests
```
