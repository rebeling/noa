# System Design for a Voice‑Driven Dialogue Assistant with Cognee

This document outlines a modular, scalable architecture for building a voice AI assistant that can ingest documents, answer questions from a knowledge graph (via Cognee) and hold natural spoken conversations with human‑like turn taking. The design emphasises open‑source components and enforces data isolation so that user‑specific datasets remain private.

---

## 1. Client & Transport Layer
*   **Client (Web/Mobile):** Captures audio from the user and renders the system’s responses. Communicates via WebSockets or WebRTC to support low‑latency streaming. Maintains a session ID and JWT or OAuth token for authentication.
*   **API Gateway / Transport Router:** Terminates TLS, validates tokens, applies rate limiting and forwards audio and messages to the appropriate internal services. This layer handles session creation and routes traffic based on user roles (Admin vs Customer).

[📋 View Tasks: Client & Transport](./superpowers/tasks/01-client-transport.md)

---

## 2. Speech Input Pipeline
*   **Voice Activity Detection (VAD):** A lightweight service (e.g., Silero‑VAD, MIT‑licensed) monitors the audio stream and triggers when speech begins or ends.
*   **Turn Detector:** Implements more advanced turn‑taking logic. Options include:
    *   Pipecat’s Smart Turn model, which uses audio cues and simple heuristics to detect finished thoughts and interruptions.
    *   TEN Turn Detection, an Apache‑licensed model with extra restrictions, which classifies utterances as finished, unfinished or “wait”.
*   **Automatic Speech Recognition (ASR):** Streams audio to a dedicated ASR service. Candidate models:
    *   Whisper (MIT license) or Qwen3‑ASR (Apache 2.0) for multilingual transcription.
    *   NVIDIA Canary‑Qwen 2.5B (CC‑BY‑4.0) if highest accuracy is required. ASR services return partial and final transcripts, which are fed into the turn detector.

[📋 View Tasks: Speech Pipeline](./superpowers/tasks/02-speech-pipeline.md)

---

## 3. Dialogue Management & Reasoning
*   **Dialogue Manager / Orchestrator:** Coordinates the conversation once a user’s turn has ended. It holds session state, context and memory. Recommended frameworks include Pipecat (BSD‑2‑Clause) or Rasa (Apache 2.0).
*   **Large Language Model (LLM):** Performs intent recognition and response generation. The LLM can be open‑source (e.g., Qwen2.5, Mistral) or an API.
*   **Knowledge Base Interface:** Generates retrieval queries for Cognee using the conversation context. The manager passes `user_id` and `dataset_id` to ensure the query targets only the authenticated user’s data.

[📋 View Tasks: Dialogue Management](./superpowers/tasks/03-dialogue-management.md)

---

## 4. Knowledge Ingestion & Retrieval
*   **Document Ingestion / Admin Interface:** Admin users upload files through a dedicated FastAPI endpoint. Files are pre‑processed by a PII/PHI redaction service before ingestion.
*   **Cognee Ingestion:** Sanitised documents are embedded and stored in Cognee’s graph and vector databases. With access control enabled (`ENABLE_BACKEND_ACCESS_CONTROL=true`), Cognee isolates data per user and dataset.
*   **Data Storage:** Graph and vector files are saved under `.cognee_system/databases/<user_uuid>/<dataset_uuid>`, ensuring that each user’s memory is private.
*   **Retrieval:** During a conversation, the dialogue manager calls Cognee’s search API to obtain relevant triples, passages or world‑model facts.

[📋 View Tasks: Knowledge Ingestion](./superpowers/tasks/04-knowledge-ingestion.md)

---

## 5. Response Synthesis
*   **Post-processing:** The LLM’s text output may be post‑processed for safety, brevity or style.
*   **Text‑to‑Speech (TTS) Service:** Converts the text response into audio. Choose an open‑source TTS engine, such as Kokoro (Apache 2.0), Coqui TTS (MPL 2.0) or XTTS‑v2 (CPML). The TTS service streams audio back to the client and supports interruption.

[📋 View Tasks: Response Synthesis](./superpowers/tasks/05-response-synthesis.md)

---

## 6. Supporting Services & Infrastructure
*   **PII/PHI Redaction Microservice:** Detects and masks sensitive information before it enters Cognee. Use Phileas or Presidio.
*   **Authentication Service:** Issues and validates tokens, manages user roles (Admin vs Customer) and dataset permissions.
*   **Monitoring & Logging:** Collects metrics (latency, error rates, VAD accuracy) and stores conversation logs for debugging.
*   **Autoscaling:** Runs compute‑heavy services (ASR, TTS, LLM) on GPU nodes. Stateless services (VAD, redaction) can run on CPU.
*   **Deployment:** Services communicate over gRPC or WebSockets within a Kubernetes cluster.

[📋 View Tasks: Infrastructure](./superpowers/tasks/06-infrastructure.md)

---

## 7. Security & Privacy Considerations
*   **Data isolation:** Cognee’s per‑user, per‑dataset storage ensures that customers cannot access another user’s data.
*   **End‑to‑end encryption:** Use TLS for client–server communication and encrypt data at rest.
*   **Model licences:** Ensure that the selected ASR and TTS models comply with your intended usage (e.g., Canary‑Qwen CC‑BY‑4.0).

[📋 View Tasks: Security & Privacy](./superpowers/tasks/07-security-privacy.md)

---

## 8. Admin vs Customer Roles
*   **Admins:** Can ingest or update documents through the ingestion API, manage datasets and configure the system.
*   **Customers:** Interact through the chat interface; they can query knowledge but cannot alter the knowledge base.

[📋 View Tasks: RBAC](./superpowers/tasks/08-rbac.md)

---

## Summary
This architecture separates concerns into modular services—audio capture, VAD/turn detection, ASR, dialogue management, knowledge retrieval and response synthesis—enabling you to swap components as better models emerge.

---

## Diagrams
*   [Overall Structure](./diagram-structure.md)
*   [Dialog Flow](./diagram-dialog.md)
