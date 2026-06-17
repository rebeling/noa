"""Cognee lifecycle — configure storage, create schema, resolve users.

Internal to ingestion. Split out of _cognee.py so that module is just the
retrieval/ingest logic; this one owns the one-time setup and the per-process
user cache. State is module-global and reset by reset_state() (dev wipe).
"""

import os
import re
import secrets

# Restrict identifiers to a safe charset — no path separators, no traversal.
_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")

# Resolved cognee Users, keyed by safe app user_id — avoids a lookup per turn.
_user_cache: dict[str, object] = {}

_cognee_configured = False
_tables_ready = False


def safe(component: str) -> str:
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


def get_cognee():
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


async def ensure_tables() -> None:
    """Create cognee's relational schema once. A freshly configured DB has
    no tables, so user lookups (the first cognee call we make) hit
    'no such table: principals'. create_db_and_tables is idempotent."""
    global _tables_ready
    if _tables_ready:
        return
    get_cognee()  # configure storage roots + LLM key first
    from cognee.infrastructure.databases.relational import create_db_and_tables

    await create_db_and_tables()
    _tables_ready = True


async def resolve_user(user_id: str):
    """Map an app user_id to a cognee User (get-or-create by synthetic
    email). Cognee 1.1 scopes every add/cognify/search to a User object,
    not a bare id — this is what makes per-tenant isolation real.

    Result cached per process so we don't re-query cognee each turn.
    """
    safe_id = safe(user_id)
    cached = _user_cache.get(safe_id)
    if cached is not None:
        return cached
    await ensure_tables()  # configure + create schema before first lookup
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


def reset_state() -> None:
    """Clear cached schema flag + users so the next call rebuilds them.

    prune_system drops the relational schema, so the cached "tables exist"
    flag becomes a lie — the next user lookup would hit 'no such table:
    principals'. Callers invoke this after a prune.
    """
    global _tables_ready
    _tables_ready = False
    _user_cache.clear()
