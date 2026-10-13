# Third-Party Notices

Noa is MIT licensed. It depends on the following software and models.
Check the lockfile for transitive dependencies before redistributing.

## Python dependencies

| Component | License | Use |
| --- | --- | --- |
| fastapi | MIT | HTTP and WebSocket API |
| uvicorn | BSD-3-Clause | ASGI server |
| jinja2 | BSD-3-Clause | HTML templating |
| pydantic-settings | MIT | Settings |
| python-jose | MIT | JWT encoding and decoding |
| python-multipart | Apache-2.0 | Login form parsing |
| bcrypt | Apache-2.0 | Password hashing |
| openai | Apache-2.0 | OpenAI API client |
| anthropic | MIT | Anthropic API client |
| pysilero-vad | MIT | Voice activity detection |
| parakeet-mlx | Apache-2.0 | ASR inference on Apple Silicon |
| piper-tts | MIT | Text-to-speech |
| kokoro-onnx | MIT | Optional text-to-speech |
| soundfile | BSD-3-Clause | WAV encoding for Kokoro |

## Models

| Model | License | Notes |
| --- | --- | --- |
| Silero VAD | MIT | bundled with pysilero-vad |
| Parakeet TDT 0.6b v3 (`mlx-community/parakeet-tdt-0.6b-v3`) | CC-BY-4.0 | downloaded from Hugging Face on first use |
| Piper voices `en_GB-jenny_dioco`, `de_DE-thorsten` | MIT (Piper); voice datasets carry their own terms, see each `.onnx.json` | downloaded by `make voices` |
| Kokoro v1.0 | Apache-2.0 | optional, downloaded by `make kokoro` |

## Browser assets

| Component | License |
| --- | --- |
| Tailwind CSS (CDN) | MIT |
