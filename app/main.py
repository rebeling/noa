import asyncio
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
    # Warm Kokoro in a thread so boot stays non-blocking. warmup() runs a
    # tiny synth so the ONNX graph is hot; the first user session then hits
    # a warm model. No greeting is precached — the orchestrator picks a
    # random greeting per session and synthesizes it on demand.
    await asyncio.to_thread(shared_tts.warmup)
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
