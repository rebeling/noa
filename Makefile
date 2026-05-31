.PHONY: start start-fake start-echo start-echo-piper start-echo-styletts2 start-http dev-cert install clean help download-models

help:
	@echo "Available commands:"
	@echo "  make start                - Start over HTTPS, real LLM + Kokoro TTS"
	@echo "  make start-fake           - fake-reply (debug) mode, no LLM/TTS"
	@echo "  make start-echo           - echo mode + Kokoro TTS (default)"
	@echo "  make start-echo-piper     - echo mode + Piper TTS"
	@echo "  make start-echo-styletts2 - echo mode + StyleTTS2"
	@echo "  make start-http           - plain HTTP, fake reply (localhost only)"
	@echo "  make dev-cert             - Generate a self-signed dev certificate"
	@echo "  make install              - Install dependencies using uv"
	@echo "  make clean                - Remove temporary files and caches"
	@echo ""
	@echo "Reply mode: NOA_REPLY_MODE=fake|echo|real      (default fake)"
	@echo "TTS prov:   NOA_TTS_PROVIDER=kokoro|piper|styletts2  (default kokoro)"

start: dev-cert
	@echo "Open: https://localhost:8000  (reply_mode=real, redaction OFF)"
	@echo "Graph: https://localhost:8000/api/v1/ingestion/graph"
	NOA_REPLY_MODE=real DEV_GRAPH_VIEWER=true REDACTION_ENABLED=false uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload \
		--ssl-keyfile certs/dev-key.pem --ssl-certfile certs/dev-cert.pem

start-fake: dev-cert
	@echo "Open: https://localhost:8000  (reply_mode=fake)"
	NOA_REPLY_MODE=fake DEV_GRAPH_VIEWER=true uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload \
		--ssl-keyfile certs/dev-key.pem --ssl-certfile certs/dev-cert.pem

start-echo: dev-cert
	@echo "Open: https://localhost:8000  (reply_mode=echo, tts=kokoro)"
	NOA_REPLY_MODE=echo NOA_TTS_PROVIDER=kokoro DEV_GRAPH_VIEWER=true uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload \
		--ssl-keyfile certs/dev-key.pem --ssl-certfile certs/dev-cert.pem

start-echo-piper: dev-cert
	@echo "Open: https://localhost:8000  (reply_mode=echo, tts=piper voice=$${NOA_PIPER_VOICE:-jenny})"
	NOA_REPLY_MODE=echo NOA_TTS_PROVIDER=piper DEV_GRAPH_VIEWER=true uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload \
		--ssl-keyfile certs/dev-key.pem --ssl-certfile certs/dev-cert.pem

start-echo-styletts2: dev-cert
	@echo "Open: https://localhost:8000  (reply_mode=echo, tts=styletts2)"
	NOA_REPLY_MODE=echo NOA_TTS_PROVIDER=styletts2 DEV_GRAPH_VIEWER=true uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload \
		--ssl-keyfile certs/dev-key.pem --ssl-certfile certs/dev-cert.pem

start-http:
	NOA_REPLY_MODE=fake uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

dev-cert:
	@mkdir -p certs
	@if [ ! -f certs/dev-key.pem ]; then \
		openssl req -x509 -newkey rsa:2048 -nodes \
			-keyout certs/dev-key.pem -out certs/dev-cert.pem \
			-days 365 -subj "/CN=localhost" \
			-addext "subjectAltName=DNS:localhost,IP:127.0.0.1" ; \
		echo "Self-signed dev cert created in certs/" ; \
	else \
		echo "certs/dev-cert.pem already exists" ; \
	fi

install:
	uv sync

download-models:
	@echo "Downloading Kokoro v1.0 models (Standard)..."
	curl -L -o kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
	curl -L -o voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

clean:
	rm -rf .venv
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -f temp_*.txt ingest_*.txt
