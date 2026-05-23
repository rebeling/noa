# Third-Party Notices

This project depends on third-party open-source software. The list below covers
the direct runtime dependencies and browser assets currently referenced by this
repository. Transitive dependencies should be audited from the lockfile before
shipping a packaged application, container image, or binary distribution.

This notice file is informational and does not replace the original license
texts from each project.

## Python Dependencies

| Component | License | Use |
| --- | --- | --- |
| bcrypt | Apache-2.0 | Password hashing |
| cognee | Apache-2.0 | Knowledge graph and memory |
| fastapi | MIT | HTTP and WebSocket API framework |
| faster-whisper | MIT | Speech-to-text inference |
| jinja2 | BSD | HTML templating |
| kokoro-onnx | MIT | Text-to-speech wrapper |
| openai | Apache-2.0 | OpenAI API client |
| pipecat-ai | BSD-2-Clause | Voice and multimodal pipeline framework |
| presidio-analyzer | MIT | PII/PHI detection |
| presidio-anonymizer | MIT | PII/PHI anonymization |
| pydantic-settings | MIT | Application settings |
| python-jose | MIT | JWT encoding and decoding |
| python-multipart | Apache-2.0 | Multipart form parsing |
| soundfile | BSD-3-Clause | Audio file handling |
| torch | BSD-style / BSD-3-Clause | Tensor and ML runtime |
| torchaudio | BSD-style / BSD-3-Clause | Audio ML utilities |
| uvicorn | BSD-3-Clause | ASGI server |

## Browser Assets

| Component | License | Use |
| --- | --- | --- |
| htmx | BSD-2-Clause | HTML-driven browser interactions |
| Tailwind CSS | MIT | Utility CSS framework |
| Fraunces font | SIL Open Font License 1.1 | UI font |
| Space Mono font | SIL Open Font License 1.1 | UI font |

## Model And Native Library Notes

- `kokoro-onnx` is MIT licensed, while Kokoro model files may carry separate
  model licenses. Keep model license files with any redistributed model weights.
- `soundfile` uses `libsndfile`; if you bundle native `libsndfile` binaries,
  include the applicable `libsndfile` license notices and comply with its terms.

## Distribution Checklist

Before distributing this project outside local development:

1. Generate a complete license report from the resolved environment or lockfile.
2. Include original license texts for bundled dependencies and assets.
3. Include separate notices for model weights and native libraries.
4. Re-check licenses after dependency upgrades.
