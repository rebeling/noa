import os
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

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

        # IngestionService.ingest redacts internally — no bypass path (CLAUDE.md).
        await IngestionService().ingest(text, user_id=str(user.sub))
        status_msg = "Redacted and Ingested into Cognee"
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    if request.headers.get("HX-Request"):
        return (
            '<div class="p-4 mb-4 text-sm text-green-700 bg-green-100 '
            f'rounded-lg" role="alert">{safe_name}: {status_msg}</div>'
        )
    return {"filename": safe_name, "status": status_msg}
