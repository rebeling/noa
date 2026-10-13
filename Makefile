.PHONY: help install voices kokoro start start-fake start-echo start-http dev-cert test clean

PIPER_URL = https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0
UVICORN   = uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
TLS       = --ssl-keyfile certs/dev-key.pem --ssl-certfile certs/dev-cert.pem

help:
	@echo "  make install     - install Python deps and download Piper voices"
	@echo "  make start       - run over HTTPS with real LLM + TTS"
	@echo "  make start-fake  - run with timed stub replies (no LLM, no TTS)"
	@echo "  make start-echo  - run with echoed replies + real TTS (no LLM)"
	@echo "  make start-http  - plain HTTP, fake replies (localhost only, mic needs HTTPS elsewhere)"
	@echo "  make kokoro      - download the optional Kokoro TTS model"
	@echo "  make test        - run the unit tests"
	@echo "  make clean       - remove .venv and caches"

install: voices
	uv sync

# Piper voices: English (Jenny, GB) and German (Thorsten). ~60MB each.
voices:
	@mkdir -p voices
	@for v in en/en_GB/jenny_dioco/medium/en_GB-jenny_dioco-medium de/de_DE/thorsten/medium/de_DE-thorsten-medium; do \
		f=voices/$$(basename $$v); \
		if [ ! -f $$f.onnx ]; then \
			echo "downloading $$f.onnx"; \
			curl -sL -o $$f.onnx $(PIPER_URL)/$$v.onnx; \
			curl -sL -o $$f.onnx.json $(PIPER_URL)/$$v.onnx.json; \
		fi; \
	done

kokoro:
	curl -L -o kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
	curl -L -o voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

start: dev-cert
	@echo "Open: https://localhost:8000"
	NOA_REPLY_MODE=real $(UVICORN) $(TLS)

start-fake: dev-cert
	@echo "Open: https://localhost:8000  (fake replies)"
	NOA_REPLY_MODE=fake $(UVICORN) $(TLS)

start-echo: dev-cert
	@echo "Open: https://localhost:8000  (echo replies)"
	NOA_REPLY_MODE=echo $(UVICORN) $(TLS)

start-http:
	@echo "Open: http://localhost:8000  (fake replies)"
	NOA_REPLY_MODE=fake $(UVICORN)

dev-cert:
	@mkdir -p certs
	@if [ ! -f certs/dev-key.pem ]; then \
		openssl req -x509 -newkey rsa:2048 -nodes \
			-keyout certs/dev-key.pem -out certs/dev-cert.pem \
			-days 365 -subj "/CN=localhost" \
			-addext "subjectAltName=DNS:localhost,IP:127.0.0.1" ; \
		echo "Self-signed dev cert created in certs/" ; \
	fi

test:
	uv run python -m unittest discover -s tests

clean:
	rm -rf .venv
	find . -type d -name "__pycache__" -exec rm -rf {} +
