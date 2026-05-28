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
    # Warm Kokoro in a thread so boot stays non-blocking. First user
    # session then hits a hot model. Exposed on app.state so the
    # voice endpoint can hand it to the orchestrator.
    await asyncio.to_thread(shared_tts.warmup)
    # Run one synth to fully warm the model graph (result discarded).
    # The session greeting is NOT fixed — the orchestrator picks a random
    # greeting per session in the session language, so we don't cache one.
    await asyncio.to_thread(shared_tts.precache, "Hi, how can I help?")
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
