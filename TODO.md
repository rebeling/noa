# Project TODOs

This file tracks active development tasks, user-reported issues, and areas for improvement.

## 1. Performance & Latency
*   [ ] **Memory, new strategy:** decide and design a fast memory layer (the graph layer was removed 2026-10-02 — see `docs/superpowers/specs/2026-10-02-remove-graph-layer-pace-design.md`).
*   [ ] **Kokoro first-chunk latency:** ~600ms for a 15–20 char segment vs ~70ms for Piper. Try CoreML execution provider, or make Piper the English default (`NOA_TTS_PROVIDER=piper`, voices in `voices/`).
*   [ ] **LLM time-to-first-sentence:** 0.9–1.3s with `gpt-4o-mini`. Try a smaller/faster model via `LLM_MODEL`.
*   [x] **Detailed Turn Tracing:** `[turn ] stop_talking -> first_audio` + `[turn ] full reply` per turn; `[trace]` lines for LLM/TTS.

## 2. Dialogue & Persona
*   [ ] **Proactive follow-ups:** tune the system prompt so Noa asks one short question when it helps.

## 3. UI/UX
*   [x] **Improve "Aura" Visuals:** loader/flashes during the "processing" state.
*   [x] **Smooth State Transitions:** no jitter between idle -> listening -> processing -> speaking.

## 4. Architecture & Security
*   [ ] **Smart Turn Logic (phase 2):** semantic end-of-turn (pipecat-ai/smart-turn or LiveKit EOU) behind a `TurnProvider` contract — see `docs/proposal-improve-dialog-vad.md` §5.
*   [ ] **Testing:** Consider building a basic automated test suite for the critical paths (currently manual verification only).
