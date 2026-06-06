# Project TODOs

This file tracks active development tasks, user-reported issues, and areas for improvement.

## 1. Performance & Latency
*   [ ] **Fix TTS Startup Latency:** Investigate why TTS startup still takes too long. A `shared_tts` instance is warmed up in `app/main.py`, but we need to verify if the preloading is effective and actually skips the cold load for new sessions.
*   [ ] **Analyze "Processing" Phase:** The processing phase feels too slow for short inputs.
    *   Trace and measure the execution time of Cognee database searches.
    *   Ensure the `NOA_REPLY_MODE` is not inadvertently falling back to "fake" or "echo" modes, which introduce artificial delays (e.g., `_FAKE_PROCESSING_SECS`).
*   [ ] **Detailed Turn Tracing:** Implement structured logging to capture the exact duration of each step in a conversation turn (VAD detection -> ASR -> Knowledge Retrieval -> LLM Generation -> TTS stream start). This will help isolate bottlenecks.

## 2. Dialogue & Persona
*   [ ] **Proactive Information Gathering:** Update the LLM system prompt (`app/dialogue/_llm.py`) so Noa proactively asks the user questions to fill its memory and get to know the person it is speaking with.
*   [ ] **Enhance Knowledge Awareness:** Update Noa's system prompt so it explicitly knows that:
    *   It can store and **correct** existing information.
    *   This capability is restricted to admins (it should be aware of the difference between an admin and a standard user when discussing its capabilities).
*   [ ] **Improve Question Detection:** Enhance the heuristic question detector (`_looks_like_question` in `app/orchestrator.py`) with a lightweight classifier or better logic to more accurately determine when a Cognee knowledge graph lookup is necessary.

## 3. UI/UX
*   [x] **Improve "Aura" Visuals:** Update the frontend to provide a better visual indicator (e.g., a loader or flashes) during the "processing" state.
*   [x] **Smooth State Transitions:** Fix the visual jitter in the UI when transitioning between states (idle -> listening -> processing -> speaking).

## 5. User-Reported Issues (2026-06-05)
*   [x] **Duplicate response text in transcript:** Reply bubble showed the same phrase twice (text only — audio spoken once). Cause: `_reply_with_tts` sent the first sentence as `{"type":"response","text": sentence+"..."}` *and* the full reply again at the end; each `response` message opens a new bubble in `voice.html`. Fix: dropped the intermediate text sends; the text bubble is now filled once from the final full reply. TTS sentence streaming unchanged.
*   [x] **Noa unaware of Cognee memory layer:** System prompt (`_llm.py`) now states it has a persistent per-user Cognee knowledge-graph memory, that stored facts survive across sessions and are auto-retrieved as context, and how the user stores (wake-phrase) vs recalls (ask).
*   [x] **Basic dialogue rules / greeting loop:** Added a "Conversation flow" block to the system prompt: already greeted at session start, never greet again, on a bare greeting/small-talk reply acknowledge briefly and move on instead of looping greetings.
*   [x] **Recall never fires for imperative phrasings (looked like "no memory access"):** Storage + cognee retrieval + LLM-uses-context all verified working in isolation. Real cause: the `_looks_like_question` gate returned False for non-question recall requests ("tell me about X", "remind me ...", "recall ...", "erzähl mir von ...", "was weißt du über ..."), so the orchestrator skipped the Cognee lookup entirely and Noa answered from nothing. Added `_RECALL_RE` (EN+DE imperative/memory-directed phrasings) OR-ed into the gate.
*   [x] **Filler phrase repeats too often:** Expanded EN/DE filler pools to 10 each and added `_pick_filler` with no-immediate-repeat (session-scoped `last_filler`), so the same line never plays twice in a row.
*   [x] **Shared memory for all users (OVERRIDES CLAUDE.md isolation rule):** Per explicit user decision, all sessions now share ONE memory. Added `_SHARED_TENANT="shared"` + `_tenant()` in `app/ingestion/_cognee.py`; every public entry (`add_document`, `query_with_meta`, `visualize`) collapses the caller's `user_id` to it, so any fact stored by anyone is recalled by everyone. Single chokepoint — no call site escapes. Set `_SHARED_TENANT=None` to restore per-user isolation. Old per-user data wiped via `reset()`. **NOTE:** this deliberately breaks the "Data isolation is a hard requirement" rule in CLAUDE.md — update CLAUDE.md/RBAC docs if this is permanent.

## 4. Architecture & Security
*   [ ] **Smart Turn Logic:** Implement Pipecat's Smart Turn logic to handle conversational interruptions more gracefully.
*   [ ] **RBAC Audit:** Ensure all Cognee ingestion APIs are correctly gated behind Admin-only tokens and that data isolation is properly enforced.
*   [ ] **Testing:** Consider building a basic automated test suite for the critical paths (currently manual verification only).
