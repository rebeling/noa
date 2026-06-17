# Latency Analysis & Performance Overview (2026-06-05)

Based on session logs, here is the breakdown of the most significant system bottlenecks.

## Key Observations

1. **Knowledge Ingestion (Cognee): SEVERE BOTTLENECK**
   - Saving a new fact took **63.5 seconds**. This is currently the slowest operation in the system.

2. **Knowledge Retrieval (Cognee Search): MAJOR BOTTLENECK**
   - Graph search times ranged from **4 to 8 seconds**, adding significant delay to every RAG-dependent turn.

3. **Total Turnaround (User Stop -> Bot Speaks):**
   - Consistent latency of **10 to 12 seconds**.
   - **Critical Path:** Currently, the system operates **sequentially**: (Wait for full Cognee search) -> (Wait for full LLM response) -> (Wait for full TTS synthesis). This "One-Shot" approach compounds latency at every step.
   - *Drivers:* Cognee search (4-8s) and the lack of sentence-level streaming for TTS (2.5-11s).

4. **Text-to-Speech (TTS): CRITICAL STREAMING GAP**
   - First-chunk availability varies wildly (**2.5 to 11.4 seconds**) because the system waits for the **entire LLM reply** before starting synthesis.
   - **Finding:** Kokoro is fast, but waiting for a 3-sentence LLM reply before starting the first audio byte adds unnecessary seconds of dead air.

5. **Speech Recognition (ASR): Moderate**
   - Final transcription is usually fast (~1.5s) but occasionally spikes to **4-8 seconds**.

6. **LLM Generation: Fast**
   - Producing the first sentence takes **~1 to 2.5 seconds**.

7. **Boot & Warmup: Fast**
   - Application startup is efficient at **~4.5 seconds**.

## Summary of Bottlenecks (Ranked by Latency)

| Step | Average/Peak Time | Impact |
| :--- | :--- | :--- |
| **Ingestion** | ~63s | Extremely slow knowledge updates |
| **Cognee Search** | 4-8s | Delay before starting any response |
| **TTS (First Chunk)**| 2.5-11s | Delay before audio playback begins |
| **ASR Finalization** | 1.5-8s | Variable delay in understanding intent |
| **LLM (First Sentence)** | 1-2.5s | Minimal impact on initial latency |

## Run 2: After Adjustments & Error State (2026-06-05)

A second trace was analyzed after initial adjustments.

### Key Observations

-   **Total Turnaround (TTFA):** Decreased to **5.3s - 9.0s**.
-   **Cognee Search Error:** Search latency dropped to **~200-300ms**, but this was due to a `DatasetNotFoundError (404)`. The search was fast because it failed immediately. This indicates a critical bug in dataset resolution.
-   **Remaining Latency:** With Cognee failing fast, the remaining **5-9 second delay** is confirmed to be almost entirely caused by the **lack of sentence-level streaming for TTS**.
-   **ASR Jitter:** One partial transcription spike hit **RTF 2.41** (1.8s for 0.76s of audio), showing momentary CPU/GPU contention.

### Comparison

| Metric | Run 1 | Run 2 (Error State) | Target |
| :--- | :--- | :--- | :--- |
| **Cognee Search** | 4-8s | 0.2s (failed) | < 0.5s |
| **TTFA (Total)** | 10-12s | 5.3-9s | < 2s |

## Run 3: Fixes Applied (2026-06-17)

Three targeted changes to cut the two worst offenders (Cognee retrieve + ingest):

1. **Live retrieval no longer pays for Cognee's own LLM.** Session turns
   (`COGNEE_SESSIONS=true`) used to force `SearchType.GRAPH_COMPLETION` on every
   turn — a second LLM call inside Cognee whose generated answer we discard
   (`only_context=True`). Sessions now use the same fast per-intent routing as
   non-session turns; only `relationship`-phrased queries still use graph
   completion. Expected: live `recall`/`search` drops from 4–8s to sub-second.
2. **Faster fact ingestion.** `add_document` now calls `remember(...,
   self_improvement=False)`, dropping the follow-up reconciliation LLM pass (the
   main cost in the ~63s ingest). Base cognify + uuid5 entity dedup still run.
   Ingestion is already off the live path (orchestrator backgrounds it), so this
   makes facts queryable sooner / frees the worker faster — it does not change
   perceived speaking latency.
3. **Tighter prompt memory rules** (~16 lines → ~4): cut the sub-rules that made
   Noa lecture users on wake-phrase syntax, which produced rambling multi-sentence
   replies against the 1–2 sentence cap.

## Conclusion
Reducing first‑chunk latency in a voice agent requires more than just a fast TTS model. It demands an end‑to‑end streaming architecture that overlaps ASR, LLM, TTS and playback. For open‑source, local deployment in English, Piper and Kokoro currently provide the fastest first‑chunk performance, delivering audio in under 100–300 ms on commodity hardware. Chatterbox‑Turbo offers a good compromise between speed and expressiveness with sub‑200 ms latency. NeuTTS Air demonstrates that high‑quality voice cloning can be done on‑device in real time. Whichever model you choose, stream the LLM output sentence by sentence and pre‑load the model to ensure your agent responds as quickly as a human.
