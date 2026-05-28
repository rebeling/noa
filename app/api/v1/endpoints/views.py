import re

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.security import create_access_token

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()

# Same safe charset as ingestion._cognee._safe — the chosen user becomes a
# cognee tenant id, so it must not contain path separators/traversal.
_UNSAFE_USER = re.compile(r"[^A-Za-z0-9_-]")


def _safe_user(raw: str) -> str:
    cleaned = _UNSAFE_USER.sub("_", (raw or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned or "dev"

@router.get("/ingestion", response_class=HTMLResponse)
async def ingestion_page(request: Request):
    return templates.TemplateResponse(request, "ingestion.html", {"title": "Ingestion", "page": "ingestion"})

@router.get("/voice", response_class=HTMLResponse)
async def voice_page(request: Request, user: str = "dev", role: str = "admin"):
    # Dev-only: mint a JWT and inject it so the voice WebSocket can
    # authenticate without a login UI. Not production auth — see
    # docs/superpowers/specs/2026-05-22-voice-ws-dev-token-design.md
    # `user` (?user=) becomes the JWT subject → the cognee tenant, so
    # switching it demos per-user knowledge isolation. `role` (?role=)
    # picks admin (can ingest) vs customer (query only) to demo RBAC.
    current_user = _safe_user(user)
    current_role = role.lower() if role.lower() in ("admin", "customer") else "admin"
    ws_token = create_access_token(subject=current_user, role=current_role)
    return templates.TemplateResponse(
        request,
        "voice.html",
        {
            "title": "Dialogue",
            "page": "dialogue",
            "ws_token": ws_token,
            "current_user": current_user,
            "current_role": current_role,
        },
    )

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "ingestion.html", {"title": "Dashboard", "page": "ingestion"})
