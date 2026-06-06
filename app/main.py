import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from app.core.config import settings
from app.api.v1 import api_router
from app.synthesis import SynthesisService

# Process-wide TTS instance: model load is heavy, so warm one Kokoro
# graph at boot and reuse it across sessions. Sessions still construct
# their own SynthesisService, but the orchestrator should hand them
# this shared instance to skip the per-session cold load.
shared_tts = SynthesisService()


@asynccontextmanager
async def lifespan(app_: FastAPI):
    # Warm Kokoro so ONNX graphs / kernels are hot before the first user-visible
    # call. This reduces the first-reply latency from ~5s to <1s.
    t0 = time.perf_counter()
    try:
        # warmup() synth's "hi." — we await it directly in the lifespan to
        # ensure the model is truly hot before the server accepts connections.
        await asyncio.to_thread(shared_tts.warmup)
        print(f"[boot] TTS preloaded in {(time.perf_counter()-t0)*1000:.0f}ms")
    except Exception as e:
        print(f"[boot] TTS preload failed: {e}")
    
    app_.state.shared_tts = shared_tts
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# Explicit CORS allowlist — no wildcard (unsafe with credentials).
# Origins are configured via CORS_ORIGINS in settings.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/")
async def root():
    return RedirectResponse(url=f"{settings.API_V1_STR}/voice")
