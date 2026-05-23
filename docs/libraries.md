# Libraries by Area

Every third-party library Noa uses, grouped by the architecture area it
serves. Areas map to [`system-design.md`](../system-design.md).

Source of truth for versions: [`pyproject.toml`](../pyproject.toml)
(Python deps) and the `<script>` tags in
[`app/templates/base.html`](../app/templates/base.html) (frontend).
This file is a guide — when a dependency changes, update both.

## Frontend (client & UI)

| Library | Version | Role |
|---------|---------|------|
| **htmx** | 1.9.10 | Server-driven UI interactions without a SPA framework. Loaded via CDN. |
| **Tailwind CSS** | CDN (play build) | Utility-first styling. Loaded via CDN. |
| Browser Web APIs | — | `getUserMedia` (mic, with `echoCancellation`), `AudioContext`, `WebSocket` — native, no library. The voice aura is hand-written canvas/CSS. |

Note: the voice client is plain JS in [`voice.html`](../app/templates/voice.html) —
no build step, no npm. htmx + Tailwind are pulled from CDN at runtime.

## Backend (web framework & transport)

| Library | Version | Role |
|---------|---------|------|
| **FastAPI** | >=0.136.1 | HTTP + WebSocket framework. API gateway, routing, dependency injection. |
| **Uvicorn** | >=0.47.0 | ASGI server that runs the FastAPI app. |
| **Jinja2** | >=3.1.6 | Server-side HTML templating (`app/templates/`). |
| **python-multipart** | >=0.0.29 | Parses `multipart/form-data` — file uploads, OAuth form login. |
| **pydantic-settings** | >=2.14.1 | Typed config from `.env` (`app/core/config.py`), with validators. |

## ASR — speech input

| Library | Version | Role |
|---------|---------|------|
| **faster-whisper** | >=1.2.1 | Whisper ASR (CTranslate2 backend). `base` model, int8 CPU. Partial + final transcripts. |
| **torch** | >=2.12.0 | Tensor runtime backing the speech stack. |
| **torchaudio** | >=2.11.0 | Audio I/O / transforms for the speech path. |
| **NumPy** | (transitive) | PCM buffer math; amplitude VAD in `speech.py` is pure NumPy. |

VAD is currently a NumPy amplitude threshold (no neural VAD library). The
design names Silero-VAD as a candidate upgrade — not yet a dependency.

## TTS — response synthesis

| Library | Version | Role |
|---------|---------|------|
| **kokoro-onnx** | >=0.5.0 | Kokoro TTS via ONNX runtime. Text → speech audio. |
| **soundfile** | >=0.13.1 | Encodes synthesized samples to WAV bytes for streaming. |

Kokoro is Apache-2.0 — license fits intended use (see CLAUDE.md model-license rule).

## Dialogue processing & orchestration

| Library | Version | Role |
|---------|---------|------|
| **pipecat-ai** | >=1.2.1 | Voice-agent orchestration framework (session state, pipeline). |
| **openai** | >=2.37.0 | LLM client (`AsyncOpenAI`) for intent + response generation. |
| asyncio | stdlib | The FSM in `orchestrator.py` — non-blocking receive loop, cancellable work tasks, barge-in. |

Current `orchestrator.py` runs a hand-written asyncio FSM; the LLM call is
stubbed and processing time is simulated. Pipecat is a declared dependency
for the fuller orchestration layer.

## Knowledge ingestion & retrieval

| Library | Version | Role |
|---------|---------|------|
| **cognee** | >=1.1.0 | Per-user knowledge graph + vector store. Ingestion and retrieval. Run with `ENABLE_BACKEND_ACCESS_CONTROL=true`. |

## PII / PHI redaction

| Library | Version | Role |
|---------|---------|------|
| **presidio-analyzer** | >=2.2.362 | Detects PII/PHI entities in documents before ingestion. |
| **presidio-anonymizer** | >=2.2.362 | Redacts / anonymizes detected entities. |

Mandatory layer — no document reaches Cognee without passing redaction
(CLAUDE.md non-negotiable convention).

## Auth & security

| Library | Version | Role |
|---------|---------|------|
| **python-jose[cryptography]** | >=3.5.0 | JWT encode/verify (HS256). Token auth at the gateway. |
| **bcrypt** | >=4.1.0 | Password hashing for the bootstrap admin. |
| FastAPI security | (FastAPI) | `OAuth2PasswordBearer` / `OAuth2PasswordRequestForm` — login flow + bearer extraction. |
| `secrets` | stdlib | Generating the `SECRET_KEY` (see `config.py` instructions). |

RBAC (Admin ingest / Customer query-only) is enforced in FastAPI
dependencies, not a separate library.

## Tooling

| Tool | Role |
|------|------|
| **uv** | Dependency + venv management. `uv sync`, `uv run`, `uv add`. |
| **pytest** | Test runner (`uv run pytest`). |
