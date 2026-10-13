# Noa

A voice assistant you talk to in the browser. Tap the orb, speak, get a spoken answer. Interrupt it any time.

All speech runs on your Mac: Silero detects when you talk, Parakeet transcribes it, Piper speaks the reply. Only the language model is a cloud call (OpenAI or Anthropic).

## Requirements

- Apple Silicon Mac (the speech recognizer runs on the Apple GPU)
- [uv](https://github.com/astral-sh/uv)
- An OpenAI or Anthropic API key

## Run it

```bash
make install
```

Create a `.env`:

```bash
OPENAI_API_KEY=sk-...
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
```

```bash
make start
```

Open <https://localhost:8000>, accept the self-signed certificate, tap the orb.

To use Anthropic instead, set `ANTHROPIC_API_KEY` and `LLM_MODEL=claude-sonnet-5-5` in `.env`.

## How it works

```
mic ──▶ VAD (Silero) ──▶ ASR (Parakeet) ──▶ LLM (streamed) ──▶ TTS (Piper) ──▶ speaker
```

- Speech ends after 0.5 s of silence, then the reply starts.
- The LLM stream is cut into short segments and spoken as it arrives.
- Speaking over the assistant stops it and starts a new turn.
- English and German. Toggle in the top-right corner.

Details in [docs/architecture.md](docs/architecture.md).

## Options

| Variable | Default | Meaning |
| --- | --- | --- |
| `LLM_MODEL` | `gpt-4o-mini` | `claude-*` routes to Anthropic, anything else to OpenAI |
| `NOA_TTS_PROVIDER` | `piper` | `kokoro` for a richer but slower English voice (`make kokoro` first) |
| `NOA_REPLY_MODE` | `real` | `fake` or `echo` to test the pipeline without an LLM |
| `NOA_VAD` | `silero` | `amplitude` for a model-free fallback |

Measure latency without a microphone while the server runs:

```bash
uv run python scripts/ws_probe.py "Hello, how are you?"
```

## License

MIT. Model and dependency licenses are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
