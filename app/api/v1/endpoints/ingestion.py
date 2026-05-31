import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse

from app.core.security import require_role
from app.models.token import TokenPayload
from app.ingestion import IngestionService

router = APIRouter()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB cap on uploaded documents
ALLOWED_SUFFIXES = {".txt"}


@router.post("/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    # RBAC: only Admins ingest/manage datasets (CLAUDE.md non-negotiable).
    user: TokenPayload = Depends(require_role("admin")),
):
    # Validate the filename before it ever touches the filesystem.
    raw_name = file.filename or ""
    safe_name = os.path.basename(raw_name)  # strip any path components
    suffix = os.path.splitext(safe_name)[1].lower()
    if not safe_name or safe_name in {".", ".."} or "/" in safe_name or "\\" in safe_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid filename")
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Only {sorted(ALLOWED_SUFFIXES)} files supported",
        )

    # Write to an OS temp file with a generated name — the uploaded
    # filename never influences the path, defeating path traversal.
    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as buffer:
            written = 0
            while chunk := await file.read(64 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        "File exceeds size limit",
                    )
                buffer.write(chunk)

        with open(temp_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()

        await IngestionService().ingest(text, user_id=str(user.sub))
        status_msg = f"Ingested into Cognee ({len(text)} chars)"
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    if request.headers.get("HX-Request"):
        return (
            '<div class="p-4 mb-4 text-sm text-green-700 bg-green-100 '
            f'rounded-lg" role="alert">{safe_name}: {status_msg}</div>'
        )
    return {"filename": safe_name, "status": status_msg}


@router.get("/graph", response_class=HTMLResponse)
async def graph(user_id: str | None = None, dataset_name: str = "default"):
    """Dev-only, unauthenticated graph viewer — openable straight in a browser.

    Gated behind settings.DEV_GRAPH_VIEWER (off by default); when off this
    404s so it's invisible in any real deployment. It bypasses RBAC on
    purpose for local inspection — do NOT enable it where tenant data is real.

    user_id defaults to "dev" — the subject of the dev token the ingestion
    and voice pages mint — so the no-arg URL shows what you uploaded there.
    """
    from app.core.config import settings

    if not settings.DEV_GRAPH_VIEWER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    uid = user_id or "dev"
    try:
        return await IngestionService().visualize(
            user_id=uid, dataset_name=dataset_name
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@router.post("/reset")
async def reset(
    request: Request,
    # RBAC: admin-gated like upload. Also dev-flag-gated below.
    user: TokenPayload = Depends(require_role("admin")),
):
    """Wipe ALL Cognee data (every tenant). Dev reset only.

    Gated behind settings.DEV_GRAPH_VIEWER — 404s in any real deployment so
    a global wipe can't be reached there.
    """
    from app.core.config import settings

    if not settings.DEV_GRAPH_VIEWER:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await IngestionService().reset()
    status_msg = "Cognee database cleared"
    if request.headers.get("HX-Request"):
        return HTMLResponse(
            '<div class="p-4 mb-4 text-sm text-amber-700 bg-amber-100 '
            f'rounded-lg" role="alert">{status_msg}</div>'
        )
    return {"status": status_msg}
