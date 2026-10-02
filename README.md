# Noa — Voice-Driven Dialogue Assistant

A modular voice assistant for natural, real-time spoken conversation. All speech models run locally; the LLM is OpenAI or Anthropic.

## 🚀 Key Features
- **Real-Time Voice Dialogue**: local ASR (Parakeet-MLX on the Apple GPU), Silero VAD, Piper TTS (Kokoro optional), streamed segment-by-segment.
- **Natural turn-taking**: 0.5s end-of-turn, barge-in cuts the assistant mid-sentence.
- **Pluggable LLM**: OpenAI or Anthropic, selected by `LLM_MODEL`.

No memory/knowledge layer at present — removed 2026-10-02, see `docs/superpowers/specs/2026-10-02-remove-graph-layer-pace-design.md`.

## 🛠️ Technology Stack
- **Backend**: Python 3.14+, FastAPI, uv
- **LLM**: OpenAI (default `gpt-4o-mini`) or Anthropic (`claude-*`)
- **ASR**: Parakeet TDT 0.6b v3 via MLX (Apple Silicon only)
- **VAD**: Silero (pysilero-vad)
- **TTS**: Piper (default, EN+DE), Kokoro-ONNX (optional EN, `NOA_TTS_PROVIDER=kokoro`)
- **Frontend**: single voice page, vanilla JS + WebAudio

## 🏃 Quick Start

### 1. Prerequisites
- Apple Silicon Mac (Parakeet-MLX).
- [uv](https://github.com/astral-sh/uv) installed.
- OpenAI API key (or Anthropic key + `LLM_MODEL=claude-...`).

### 2. Setup
Create a `.env` file:
```bash
OPENAI_API_KEY=your_key_here
SECRET_KEY=your_strong_random_secret
```

For local voice UI development without a login token, add:
```bash
ALLOW_UNAUTHENTICATED_VOICE=true
```
Leave that setting unset outside local development so the voice WebSocket
continues to require a JWT.

Install dependencies (Piper voices ship in `voices/`; `make download-models` fetches the optional Kokoro model):
```bash
make install
```

### 3. Run
```bash
make start
```
Open https://localhost:8000 (self-signed cert; redirects to the voice page). Tap the orb, talk.

Latency probe without a mic (server must be running):
```bash
uv run python scripts/ws_probe.py "Hello, how are you?"
```

## 📁 Project Structure
- `app/api`: FastAPI route handlers (auth, voice page, voice WebSocket).
- `app/speech_input`, `app/dialogue`, `app/synthesis`: the three pipeline parts.
- `app/orchestrator.py`: wires the parts per session.
- `docs/superpowers/`: specs, plans, task checklists.

## 📋 Documentation
- [System Design](./docs/system-design.md): architecture.
- [CLAUDE.md](./CLAUDE.md) / [GEMINI.md](./GEMINI.md): agent context and conventions.
