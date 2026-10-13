import re

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.core.security import create_access_token

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()

# The chosen user becomes the JWT subject; keep it to a safe charset.
_UNSAFE_USER = re.compile(r"[^A-Za-z0-9_-]")


def _safe_user(raw: str) -> str:
    cleaned = _UNSAFE_USER.sub("_", (raw or "").strip())
    cleaned = cleaned.strip("_")
    return cleaned or "dev"


@router.get("/voice", response_class=HTMLResponse)
async def voice_page(request: Request, user: str = "dev", role: str = "admin"):
    # Dev-only: mint a JWT and inject it into the page so the voice
    # WebSocket can authenticate without a login UI. Not production auth.
    # `user` (?user=) becomes the JWT subject; `role` (?role=) is carried in
    # the token but gates nothing in the voice path today.
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
