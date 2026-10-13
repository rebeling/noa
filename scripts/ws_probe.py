"""Text-input latency probe for the voice WebSocket.

Starts no server: run `make start-http` (or uvicorn on PORT) first, then
    uv run python scripts/ws_probe.py "Hello, how are you?" "What time is it?"
Prints every message with ms since the turn was sent and the time of the
first audio byte. Uses the dev token the voice page mints.

Env: NOA_PROBE_BASE (default http://127.0.0.1:8000), NOA_PROBE_LANG (en),
     NOA_PROBE_TIMEOUT seconds per turn (30).
"""

import asyncio
import json
import os
import re
import sys
import time
import urllib.request

import websockets

BASE = os.environ.get("NOA_PROBE_BASE", "http://127.0.0.1:8000")
LANG = os.environ.get("NOA_PROBE_LANG", "en")
TURN_TIMEOUT = float(os.environ.get("NOA_PROBE_TIMEOUT", "30"))


def dev_token() -> str:
    html = urllib.request.urlopen(f"{BASE}/api/v1/voice?user=dev&role=admin").read().decode()
    return re.search(r'name="ws-token" content="([^"]+)"', html).group(1)


async def drain_until_waiting(ws, t0: float, timeout: float) -> tuple[int, float | None]:
    audio = 0
    first_audio = None
    while time.perf_counter() - t0 < timeout:
        remaining = timeout - (time.perf_counter() - t0)
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except TimeoutError:
            print("  (timeout)")
            break
        dt = (time.perf_counter() - t0) * 1000
        if isinstance(msg, bytes):
            audio += len(msg)
            if first_audio is None:
                first_audio = dt
                print(f"  [{dt:6.0f}ms] FIRST AUDIO")
            continue
        d = json.loads(msg)
        print(f"  [{dt:6.0f}ms] {d.get('type')}: {str(d.get('text', ''))[:120]}")
        if d.get("type") == "status" and d.get("text") == "Waiting...":
            break
    return audio, first_audio


async def main(turns: list[str]) -> None:
    ws_base = BASE.replace("http", "ws", 1)
    url = f"{ws_base}/api/v1/voice/ws?token={dev_token()}&lang={LANG}"
    async with websockets.connect(url, max_size=None) as ws:
        print(">>> greeting")
        await drain_until_waiting(ws, time.perf_counter(), TURN_TIMEOUT)
        for text in turns:
            print(f"\n>>> {text!r}")
            t0 = time.perf_counter()
            await ws.send(json.dumps({"type": "text_input", "text": text}))
            audio, first = await drain_until_waiting(ws, t0, TURN_TIMEOUT)
            print(f"  audio_bytes={audio} first_audio_ms={first and round(first)}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["Hello, how are you today?"]))
