from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os

from app.core.security import create_access_token

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()

@router.get("/ingestion", response_class=HTMLResponse)
async def ingestion_page(request: Request):
    return templates.TemplateResponse(request, "ingestion.html", {"title": "Ingestion", "page": "ingestion"})

@router.get("/voice", response_class=HTMLResponse)
async def voice_page(request: Request):
    # Dev-only: mint a JWT and inject it so the voice WebSocket can
    # authenticate without a login UI. Not production auth — see
    # docs/superpowers/specs/2026-05-22-voice-ws-dev-token-design.md
    ws_token = create_access_token(subject="dev", role="admin")
    return templates.TemplateResponse(
        request,
        "voice.html",
        {"title": "Dialogue", "page": "dialogue", "ws_token": ws_token},
    )

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "ingestion.html", {"title": "Dashboard", "page": "ingestion"})
