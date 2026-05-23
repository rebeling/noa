"""Cognee graph/vector store access — internal to ingestion.

Per-tenant isolation: every add/cognify/search carries user_id +
dataset_name. The _safe() sanitizer keeps tenant identifiers from ever
forming path separators or traversal sequences.
"""

import os
import re
import tempfile

# Restrict identifiers to a safe charset — no path separators, no traversal.
_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")


def _safe(component: str) -> str:
    """Sanitize a tenant identifier for safe use in dataset names.

    Rejects path-traversal inputs outright (rather than silently
    mangling them) so a bad identifier surfaces as an error at the
    call site instead of becoming a wrong-but-valid dataset name.
    """
    raw = (component or "").strip()
    if not raw or raw in {".", ".."}:
        raise ValueError(f"Invalid identifier: {component!r}")
    cleaned = _SAFE_ID.sub("_", raw)
    # All characters were separators/illegal — nothing usable remains.
    if not cleaned.strip("_"):
        raise ValueError(f"Invalid identifier: {component!r}")
    return cleaned


def _get_cognee():
    import cognee

    return cognee


async def add_document(redacted_text: str, user_id: str, dataset_name: str) -> bool:
    """Write already-redacted text to Cognee, scoped to one tenant.

    Caller MUST pass redacted text — this function does not redact.
    """
    user_id = _safe(user_id)
    dataset_name = _safe(dataset_name)
    cognee = _get_cognee()
    # Generated temp path — tenant identifiers never build the filename.
    fd, temp_file = tempfile.mkstemp(prefix=f"ingest_{user_id}_", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(redacted_text)
        await cognee.add(temp_file, dataset_name=dataset_name, user_id=user_id)
        await cognee.cognify(datasets=[dataset_name], user_id=user_id)
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)
    return True


async def search(query: str, user_id: str, dataset_name: str) -> str:
    """Query Cognee scoped to one tenant's dataset."""
    user_id = _safe(user_id)
    dataset_name = _safe(dataset_name)
    cognee = _get_cognee()
    try:
        results = await cognee.search(
            query_text=query, datasets=[dataset_name], user_id=user_id
        )
        return str(results)
    except Exception as e:  # noqa: BLE001
        print(f"Cognee search error: {e}")
        return ""
