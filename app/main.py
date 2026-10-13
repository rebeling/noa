import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import api_router
from app.core.config import settings
from app.synthesis import SynthesisService

# One process-wide English TTS, warmed at boot and shared by sessions so
# the first reply skips the model cold load.
shared_tts = SynthesisService()


@asynccontextmanager
async def lifespan(app_: FastAPI):
    t0 = time.perf_counter()
    try:
        await asyncio.to_thread(shared_tts.warmup)
        print(f"[boot] TTS preloaded in {(time.perf_counter() - t0) * 1000:.0f}ms")
    except Exception as e:  # noqa: BLE001
        print(f"[boot] TTS preload failed: {e}")
    app_.state.shared_tts = shared_tts
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
async def root():
    return RedirectResponse(url=f"{settings.API_V1_STR}/voice")
