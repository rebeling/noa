"""Cognee graph/vector store access — internal to ingestion.

Per-tenant isolation: every add/cognify/search carries user_id +
dataset_name. The _safe() sanitizer keeps tenant identifiers from ever
forming path separators or traversal sequences.
"""

import os
import re
import secrets
import tempfile

# Restrict identifiers to a safe charset — no path separators, no traversal.
_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")

# Cap retrieved context so it can't blow the downstream LLM prompt.
_MAX_CONTEXT_CHARS = 4000

# Resolved cognee Users, keyed by app user_id — avoids a lookup per turn.
_user_cache: dict[str, object] = {}


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


_cognee_configured = False


def _get_cognee():
    """Import cognee and configure its storage roots + LLM key once.

    Storage is project-local per CLAUDE.md (.cognee_system/databases/...)
    rather than the default buried inside site-packages, which isn't
    created and fails with 'unable to open database file'.
    """
    global _cognee_configured
    import cognee

    if not _cognee_configured:
        from app.core.config import settings

        # cognee reads access control from os.environ, not our Settings object
        # (see cognee.context_global_variables.backend_access_control_enabled).
        # Export the setting so the per-tenant isolation CLAUDE.md mandates is
        # enforced from our config — never left to whether .env happened to set
        # the bare env var.
        os.environ["ENABLE_BACKEND_ACCESS_CONTROL"] = (
            "true" if settings.ENABLE_BACKEND_ACCESS_CONTROL else "false"
        )

        base = os.path.join(os.getcwd(), ".cognee_data")
        data_dir = os.path.join(base, "data")
        system_dir = os.path.join(base, "system")
        # cognee opens its sqlite metadata DB at <system>/databases without
        # creating the tree first, so pre-create both roots and the db dir.
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(os.path.join(system_dir, "databases"), exist_ok=True)
        cognee.config.data_root_directory(data_dir)
        cognee.config.system_root_directory(system_dir)
        if settings.OPENAI_API_KEY:
            cognee.config.set_llm_api_key(settings.OPENAI_API_KEY)
        _cognee_configured = True
    return cognee


_tables_ready = False


async def _ensure_tables() -> None:
    """Create cognee's relational schema once. A freshly configured DB has
    no tables, so user lookups (the first cognee call we make) hit
    'no such table: principals'. create_db_and_tables is idempotent."""
    global _tables_ready
    if _tables_ready:
        return
    _get_cognee()  # configure storage roots + LLM key first
    from cognee.infrastructure.databases.relational import create_db_and_tables

    await create_db_and_tables()
    _tables_ready = True


async def _resolve_user(user_id: str):
    """Map an app user_id to a cognee User (get-or-create by synthetic
    email). Cognee 1.1 scopes every add/cognify/search to a User object,
    not a bare id — this is what makes per-tenant isolation real.

    Result cached per process so we don't re-query cognee each turn.
    """
    safe_id = _safe(user_id)
    cached = _user_cache.get(safe_id)
    if cached is not None:
        return cached
    await _ensure_tables()  # configure + create schema before first lookup
    from cognee.modules.users.methods import create_user, get_user_by_email

    # cognee validates the email; reserved TLDs (.local/.test/.invalid) are
    # rejected, so use a normal-looking domain. These accounts are synthetic
    # and never receive mail.
    email = f"{safe_id}@noa-users.com"
    try:
        user = await get_user_by_email(email)
    except Exception:  # noqa: BLE001
        user = None
    if user is None:
        # Random password — these synthetic accounts are never logged into.
        user = await create_user(
            email, secrets.token_urlsafe(24), is_verified=True
        )
    _user_cache[safe_id] = user
    return user


async def add_document(text: str, user_id: str, dataset_name: str) -> bool:
    """Write text to Cognee, scoped to one tenant."""
    safe_user_id = _safe(user_id)
    dataset_name = _safe(dataset_name)
    cognee = _get_cognee()
    user = await _resolve_user(user_id)
    # Generated temp path — tenant identifiers never build the filename.
    fd, temp_file = tempfile.mkstemp(prefix=f"ingest_{safe_user_id}_", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        await cognee.add(temp_file, dataset_name=dataset_name, user=user)
        await cognee.cognify(datasets=[dataset_name], user=user)
    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)
    return True


async def search(query: str, user_id: str, dataset_name: str) -> str:
    """Retrieve context from a tenant's knowledge graph.

    Returns raw retrieved context (only_context=True) for the caller's
    LLM to ground on — not a cognee-synthesized answer. Returns "" on any
    miss/error so the caller can degrade to plain chat.
    """
    dataset_name = _safe(dataset_name)
    cognee = _get_cognee()
    try:
        from cognee.modules.search.types import SearchType

        user = await _resolve_user(user_id)
        results = await cognee.search(
            query_text=query,
            query_type=SearchType.GRAPH_COMPLETION,
            datasets=[dataset_name],
            user=user,
            only_context=True,
            top_k=5,
        )
        # results is a list of SearchResult-ish items; flatten to text.
        parts = [str(r).strip() for r in (results or []) if str(r).strip()]
        context = "\n\n".join(parts).strip()
        return context[:_MAX_CONTEXT_CHARS]
    except Exception as e:  # noqa: BLE001
        print(f"Cognee search error: {e}")
        return ""


async def visualize(user_id: str, dataset_name: str) -> str:
    """Render one tenant's knowledge graph as a standalone HTML page.

    Scoped to (user, dataset) via cognee's multi-user visualizer so the
    output respects the same per-tenant isolation as add/search — never
    the global graph. Returns the HTML string; raises if the dataset
    doesn't exist for this user (caller maps that to a 404).
    """
    dataset_name = _safe(dataset_name)
    _get_cognee()
    await _ensure_tables()
    from cognee.api.v1.visualize import visualize_multi_user_graph
    from cognee.modules.data.methods import get_datasets_by_name

    user = await _resolve_user(user_id)
    datasets = await get_datasets_by_name(dataset_name, user.id)
    if not datasets:
        raise ValueError(f"No dataset {dataset_name!r} for this user")
    return await visualize_multi_user_graph([(user, datasets[0])])


async def reset() -> None:
    """Wipe ALL cognee data — every tenant's documents, graph and vectors.

    Global, not per-tenant: this is a dev reset, not a delete-my-dataset.
    Also clears the resolved-user cache so subsequent calls re-create users.
    """
    cognee = _get_cognee()
    await _ensure_tables()
    await cognee.prune.prune_data()
    await cognee.prune.prune_system(graph=True, vector=True, metadata=True)
    _user_cache.clear()
