# Overall Structure

Noa voice pipeline, modeled on the layered voice-AI agent architecture: a horizontal speech spine (VAD → ASR → NLU → LLM → TTS) with a Dialogue Manager holding state, Cognee as the knowledge base, and observability spanning the stack.

```mermaid

---
config:
  layout: dagre
---
flowchart LR
    A["User"] -- Speech --> B("VAD")
    B -- Audio --> C("ASR")
    C -- Text --> D{"NLU & Intent"}
    D -- Query --> E[("Cognee")]
    E -- Facts --> F("LLM & Tools")
    D -- Direct --> F
    F -- Response --> G("TTS")
    G -- Audio --> A

     A:::royal
     B:::light
     C:::heavy
     E:::support
     F:::heavy
     G:::light
    classDef heavy  fill:#3a3a3a,stroke:#222,color:#fff,font-weight:bold
    classDef light  fill:#7ec0f5,stroke:#4a90d0,color:#0a2540,font-weight:bold
    classDef royal  fill:#1565e0,stroke:#0d47a1,color:#fff,font-weight:bold
    classDef support fill:#d9d9d9,stroke:#999,color:#222
    style G fill:#000000,color:#ffffff

```

### Layers

1.  **User:** speaks → **Audio Input** captures the stream.
2.  **VAD** (Voice Activity Detection): detects speech start/end, gates the pipeline.
3.  **ASR** (Automatic Speech Recognition): speech → text (compute-heavy).
4.  **NLU & Intent** (Natural Language Understanding): classifies intent, routes the turn.
5.  **LLM & Tools** (Large Language Model): reasoning + response generation (compute-heavy).
6.  **TTS** (Text-to-Speech): text → speech, streamed back.

### Cross-cutting

*   **Dialogue Manager** holds session **State & Context**; fed by VAD (turn signals), ASR (transcripts), and the **Cognee Knowledge Base** (per-tenant facts).
*   **Observability & Monitoring** taps the Dialogue Manager, LLM, and TTS for latency/error metrics.
```
