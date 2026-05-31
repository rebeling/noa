# Dialog Flow

The conversation as a state machine — the same states the orb animates through (idle / listening / processing / speaking). A turn cycles Listening → Processing → Speaking → Listening; barge-in and errors cut sideways.

```mermaid
%%{init: {'state': {'nodeSpacing': 120, 'rankSpacing': 160}} }%%
stateDiagram-v2
    direction TB
    [*] --> Idle

    Idle --> Listening: tap to wake / speech
    Listening --> Processing: turn end (final transcript)
    Processing --> Speaking: response ready
    Speaking --> Listening: playback done / barge-in
    Processing --> Listening: barge-in
    Listening --> Idle: tap to sleep

    Idle --> Error: connection fail
    Listening --> Error: connection fail
    Error --> Listening: retry / tap

    note right of Listening: VAD + ASR capturing
    note right of Processing: NLU → Cognee → LLM
    note right of Speaking: TTS streaming audio
```

### States

*   **Idle:** asleep, waiting. Tap (or speech) wakes it.
*   **Listening:** VAD + ASR capturing the user's speech. Ends the turn on the final transcript.
*   **Processing:** NLU → Cognee → LLM — intent, per-tenant retrieval, response generation.
*   **Speaking:** TTS streaming audio back. Returns to Listening when playback finishes.
*   **Error:** connection failed; tap retries.

### Transitions

*   **Barge-in:** user speaks during Processing or Speaking → cancel and drop straight back to Listening.
*   **Sleep:** tap while Listening → back to Idle.
