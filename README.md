# v1: Voice-Driven Dialogue Assistant

A modular, privacy-first voice assistant that can ingest documents into a knowledge graph and hold natural, real-time spoken conversations.

## 🚀 Key Features
- **Real-Time Voice Dialogue**: Low-latency ASR (Whisper) and TTS (Kokoro) orchestrated via Pipecat.
- **Privacy-First Ingestion**: Automatic PII/PHI redaction using Microsoft Presidio before data enters the knowledge graph.
- **Knowledge Graph RAG**: Powered by Cognee for advanced reasoning over ingested documents.
- **Modern Web Dashboard**: Server-driven UI built with FastAPI, Jinja2, and HTMX.

## 🛠️ Technology Stack
- **Backend**: Python 3.14+, FastAPI
- **Orchestration**: Pipecat-AI
- **Knowledge Base**: Cognee (SQLite/LanceDB local backend)
- **AI Models**: 
  - **LLM**: OpenAI (GPT-4o)
  - **ASR**: Faster-Whisper (Local)
  - **VAD**: Silero-VAD (Local)
  - **TTS**: Kokoro-ONNX (Local)
- **Frontend**: HTMX, TailwindCSS

## 🏃 Quick Start

### 1. Prerequisites
- [uv](https://github.com/astral-sh/uv) installed.
- OpenAI API Key.

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

Install dependencies:
```bash
make install
```

### 3. Run
Start the server:
```bash
make start
```
Access the dashboard at: [http://localhost:8000/api/v1/dashboard](http://localhost:8000/api/v1/dashboard)

## 📁 Project Structure
- `app/api`: FastAPI route handlers (Auth, Ingestion, Voice).
- `app/services`: Core logic for Speech, TTS, Knowledge, and Orchestration.
- `app/templates`: HTMX/Jinja2 dashboard templates.
- `docs/superpowers/tasks/`: Detailed implementation roadmap and status.

## 📋 Documentation
- [System Design](./system-design.md): Deep dive into the architecture.
- [GEMINI.md](./GEMINI.md): Agent-specific context and conventions.
- [ESTIMATE.md](./ESTIMATE.md): Project effort and timeline breakdown.
