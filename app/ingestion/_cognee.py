"""Cognee graph/vector store access — internal to ingestion.

Per-tenant isolation: every add/cognify/search carries user_id +
dataset_name. The _safe() sanitizer keeps tenant identifiers from ever
forming path separators or traversal sequences.
"""

import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

# Restrict identifiers to a safe charset — no path separators, no traversal.
_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]")

# SHARED MEMORY MODE: every user shares ONE memory.
# The caller's user_id and dataset_name are ignored — collapsed to these
# single identifiers — so any fact stored by anyone is recalled by everyone.
# This is the ONE chokepoint: every add / search / visualize path resolves
# its tenant through _tenant() and _dataset() below.
_SHARED_USER: str | None = "shared_user"
_SHARED_DATASET: str | None = "shared_dataset"


def _tenant(user_id: str) -> str:
    """Collapse any caller user_id to the shared tenant when shared-memory
    mode is on; otherwise pass it through unchanged."""
    return _SHARED_USER if _SHARED_USER is not None else user_id


def _dataset(dataset_name: str) -> str:
    """Collapse any caller dataset_name to the shared dataset when shared-memory
    mode is on; otherwise pass it through unchanged."""
    return _SHARED_DATASET if _SHARED_DATASET is not None else dataset_name

# Cap retrieved context so it can't blow the downstream LLM prompt.
_MAX_CONTEXT_CHARS = 4000

# Resolved cognee Users, keyed by app user_id — avoids a lookup per turn.
_user_cache: dict[str, object] = {}


@dataclass(frozen=True)
class KnowledgeQueryResult:
    """Retrieved memory plus routing/debug metadata."""

    context: str
    source: str
    intent: str
    elapsed_ms: int
    search_type: str | None
    dataset_name: str
    hit_count: int
    fallback_used: bool = False


@dataclass(frozen=True)
class _LocalDocument:
    text: str
    tokens: set[str]
    data_id: str
    path: str


@dataclass(frozen=True)
class _LocalHit:
    text: str
    score: float
    data_id: str
    path: str


@dataclass
class _LocalIndex:
    docs: list[_LocalDocument]


_local_index_cache: dict[tuple[str, str], _LocalIndex] = {}
_query_cache: dict[tuple[str, str, str], KnowledgeQueryResult] = {}

_WORD_RE = re.compile(r"\b[\w]+\b", re.UNICODE)
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "about",
    "can",
    "does",
    "do",
    "for",
    "from",
    "give",
    "how",
    "in",
    "is",
    "me",
    "of",
    "on",
    "please",
    "the",
    "to",
    "was",
    "what",
    "where",
    "who",
    "why",
    "wie",
    "wo",
    "wer",
    "was",
    "warum",
    "ist",
    "sind",
    "der",
    "die",
    "das",
    "den",
    "dem",
    "ein",
    "eine",
    "einer",
    "und",
    "oder",
    "von",
    "zu",
    "im",
    "am",
    "mit",
    "mir",
    "bitte",
}
_LOCAL_MIN_SCORE = 0.45
_LOCAL_TOP_K = 3


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


def _tokenize(text: str) -> list[str]:
    return [
        token
        for token in (match.group(0).lower() for match in _WORD_RE.finditer(text))
        if len(token) >= 2 and token not in _STOP_WORDS
    ]


def _normalize_query(query: str) -> str:
    return " ".join(_tokenize(query))


def _classify_intent(query: str) -> str:
    q = query.strip().lower()
    if re.search(r'"[^"]+"|\b(exact|verbatim|literal|word.for.word)\b', q):
        return "exact_lookup"
    if re.search(r"\b(summarize|summary|overview|tl;?dr|gist)\b", q):
        return "summary"
    if re.search(r"\b(before|after|during|since|until|timeline)\b|\b\d{4}s?\b", q):
        return "temporal"
    if re.search(
        r"\b(related|connected|linked|relationship|connection|relates|verbunden)\b",
        q,
    ):
        return "relationship"
    if re.search(
        r"\b(who|what|where|which|does|is|are|wer|was|wo|welche|ist|sind)\b",
        q,
    ):
        return "fact_lookup"
    return "open_question"


def _cognee_db_path() -> Path:
    return Path(os.getcwd()) / ".cognee_data" / "system" / "databases" / "cognee_db"


def _existing_user_db_id(safe_user_id: str) -> str | None:
    db_path = _cognee_db_path()
    if not db_path.exists():
        return None
    try:
        with sqlite3.connect(db_path) as con:
            row = con.execute(
                "SELECT id FROM users WHERE email = ?",
                (f"{safe_user_id}@noa-users.com",),
            ).fetchone()
    except sqlite3.Error:
        return None
    return str(row[0]) if row else None


def _path_from_raw_location(raw_location: str) -> Path | None:
    parsed = urlparse(raw_location or "")
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    if not parsed.scheme and raw_location:
        return Path(raw_location)
    return None


def _invalidate_local_cache(safe_user_id: str, dataset_name: str) -> None:
    prefix = (safe_user_id, dataset_name)
    _local_index_cache.pop(prefix, None)
    for key in [key for key in _query_cache if key[:2] == prefix]:
        _query_cache.pop(key, None)


def _format_context(hits: list[_LocalHit]) -> str:
    parts = []
    for hit in hits:
        text = hit.text.strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts).strip()[:_MAX_CONTEXT_CHARS]


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


def _load_local_index(
    safe_user_id: str, dataset_name: str, owner_id: str
) -> _LocalIndex:
    cache_key = (safe_user_id, dataset_name)
    cached = _local_index_cache.get(cache_key)
    if cached is not None:
        return cached

    db_path = _cognee_db_path()
    if not db_path.exists():
        index = _LocalIndex(docs=[])
        _local_index_cache[cache_key] = index
        return index

    docs: list[_LocalDocument] = []
    query = """
        SELECT data.id, data.raw_data_location
        FROM datasets
        JOIN dataset_data ON dataset_data.dataset_id = datasets.id
        JOIN data ON data.id = dataset_data.data_id
        WHERE datasets.name = ? AND datasets.owner_id = ?
        ORDER BY data.created_at ASC
    """
    try:
        with sqlite3.connect(db_path) as con:
            rows = con.execute(query, (dataset_name, owner_id)).fetchall()
    except sqlite3.Error as e:
        print(f"Cognee local index DB error: {e}")
        rows = []

    for data_id, raw_location in rows:
        path = _path_from_raw_location(raw_location)
        if path is None or not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        tokens = set(_tokenize(text))
        if text and tokens:
            docs.append(
                _LocalDocument(
                    text=text,
                    tokens=tokens,
                    data_id=str(data_id),
                    path=str(path),
                )
            )

    index = _LocalIndex(docs=docs)
    _local_index_cache[cache_key] = index
    return index


def _search_local_index(index: _LocalIndex, query: str) -> list[_LocalHit]:
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return []

    hits: list[_LocalHit] = []
    for doc in index.docs:
        overlap = query_tokens & doc.tokens
        if not overlap:
            continue
        coverage = len(overlap) / len(query_tokens)
        jaccard = len(overlap) / len(query_tokens | doc.tokens)
        score = coverage + (0.2 * jaccard)
        hits.append(
            _LocalHit(
                text=doc.text,
                score=score,
                data_id=doc.data_id,
                path=doc.path,
            )
        )

    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[:_LOCAL_TOP_K]


def _should_try_local(intent: str) -> bool:
    return intent in {"fact_lookup", "exact_lookup", "open_question", "summary"}


def _local_hit_is_strong(hits: list[_LocalHit], intent: str) -> bool:
    if not hits:
        return False
    if intent == "summary":
        return True
    return hits[0].score >= _LOCAL_MIN_SCORE


async def add_document(text: str, user_id: str, dataset_name: str) -> bool:
    """Write text to Cognee, scoped to one tenant.

    Uses the v1.0 remember() entry point: it runs the full ingestion
    pipeline (normalize → graph → embed) and an Improve pass that resolves
    each fact's entities against what the graph already knows. That entity
    resolution is what the old add→cognify path tried to fake by prepending
    prior search results — a loop that re-ingested stringified search dumps
    as facts and poisoned the graph. remember() makes that hack unnecessary.
    """
    user_id = _tenant(user_id)
    dataset_name = _dataset(dataset_name)
    safe_user_id = _safe(user_id)
    dataset_name = _safe(dataset_name)
    cognee = _get_cognee()
    user = await _resolve_user(user_id)
    await cognee.remember(text, dataset_name=dataset_name, user=user)
    _invalidate_local_cache(safe_user_id, dataset_name)
    return True


# Search types cognee threads session history through (per cognee docs:
# only GRAPH_COMPLETION / RAG_COMPLETION / TRIPLET_COMPLETION use sessions).
# When the session experiment is on we force fact-style intents onto
# GRAPH_COMPLETION so a session_id actually carries conversation memory.
_SESSION_SEARCH_TYPE = "GRAPH_COMPLETION"


async def _search_cognee(
    query: str,
    user: object,
    dataset_name: str,
    intent: str,
    *,
    use_recall: bool = True,
    session_id: str | None = None,
) -> tuple[str, str, int]:
    cognee = _get_cognee()
    from cognee.modules.search.types import SearchType
    from cognee.modules.data.methods import get_datasets_by_name

    # Check if dataset exists before searching to avoid 404 error
    _t_ds = time.perf_counter()
    try:
        datasets = await get_datasets_by_name(dataset_name, user.id)
        if not datasets:
            print(f"[trace] cognee search: dataset {dataset_name!r} not found for user")
            return "", "MISS", 0
    except Exception as e:
        print(f"[trace] cognee search: error checking dataset: {e}")
        return "", "ERROR", 0
    _dt_ds = (time.perf_counter() - _t_ds) * 1000

    # Session experiment: route to GRAPH_COMPLETION (a session-eligible type)
    # so the passed session_id threads prior Q&A into the prompt. Otherwise
    # keep the latency-cheap per-intent routing.
    if session_id is not None:
        search_type = SearchType.GRAPH_COMPLETION
    elif intent == "exact_lookup":
        search_type = SearchType.CHUNKS_LEXICAL
    elif intent == "summary":
        search_type = SearchType.GRAPH_SUMMARY_COMPLETION
    elif intent == "temporal":
        search_type = SearchType.TEMPORAL
    elif intent == "relationship":
        search_type = SearchType.GRAPH_COMPLETION
    elif intent == "fact_lookup":
        search_type = SearchType.CHUNKS_LEXICAL
    else:
        search_type = SearchType.CHUNKS_LEXICAL

    top_k = 3 if search_type == SearchType.CHUNKS_LEXICAL else 5
    # session_id is only meaningful on cognee.search/recall when caching is
    # on; passed through unconditionally — cognee ignores it for non-session
    # search types and degrades gracefully if no cache backend exists.
    _api = "recall" if (use_recall and hasattr(cognee, "recall")) else "search"
    _t_call = time.perf_counter()
    if _api == "recall":
        results = await cognee.recall(
            query_text=query,
            query_type=search_type,
            datasets=[dataset_name],
            user=user,
            only_context=True,
            top_k=top_k,
            auto_route=False,
            session_id=session_id,
        )
    else:
        results = await cognee.search(
            query_text=query,
            query_type=search_type,
            datasets=[dataset_name],
            user=user,
            only_context=True,
            top_k=top_k,
            session_id=session_id,
        )
    _dt_call = (time.perf_counter() - _t_call) * 1000
    parts = [_result_text(r) for r in (results or [])]
    parts = [part for part in parts if part]
    # Phase breakdown: the cognee call dominates (vector + optional LLM);
    # dataset_check and result parsing are negligible by comparison.
    print(f"[trace] cognee phases: dataset_check={_dt_ds:.0f}ms "
          f"{_api}({search_type.value})={_dt_call:.0f}ms "
          f"top_k={top_k} results={len(parts)}")
    return "\n\n".join(parts).strip()[:_MAX_CONTEXT_CHARS], search_type.value, len(parts)


def _result_text(result: object) -> str:
    if hasattr(result, "model_dump"):
        try:
            result = result.model_dump()
        except Exception:  # noqa: BLE001
            pass
    if isinstance(result, dict):
        for key in ("text", "search_result", "context_result", "content", "answer"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        raw = result.get("raw")
        if isinstance(raw, dict):
            value = raw.get("text") or raw.get("value")
            if isinstance(value, str) and value.strip():
                return value.strip()
    text = str(result).strip()
    return text


async def query_with_meta(
    query: str, user_id: str, dataset_name: str, session_id: str | None = None
) -> KnowledgeQueryResult:
    """Retrieve memory context with source, intent and timing metadata.

    When `session_id` is set (the cognee-sessions experiment), the local
    lexical fast path and the per-query cache are bypassed: both would
    short-circuit the cognee call that threads conversation history, so a
    session turn always goes through GRAPH_COMPLETION on the cognee side.
    """
    t0 = time.perf_counter()
    user_id = _tenant(user_id)
    dataset_name = _dataset(dataset_name)
    safe_user_id = _safe(user_id)
    dataset_name = _safe(dataset_name)
    intent = _classify_intent(query)
    normalized_query = _normalize_query(query)
    cache_key = (safe_user_id, dataset_name, normalized_query)
    if session_id is None:
        cached = _query_cache.get(cache_key)
        if cached is not None:
            return KnowledgeQueryResult(
                context=cached.context,
                source="local_cache",
                intent=cached.intent,
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
                search_type=cached.search_type,
                dataset_name=cached.dataset_name,
                hit_count=cached.hit_count,
                fallback_used=cached.fallback_used,
            )

    try:
        if session_id is None and _should_try_local(intent):
            owner_id = _existing_user_db_id(safe_user_id)
            if owner_id is not None:
                index = _load_local_index(safe_user_id, dataset_name, owner_id)
                hits = _search_local_index(index, query)
                if _local_hit_is_strong(hits, intent):
                    result = KnowledgeQueryResult(
                        context=_format_context(hits),
                        source="local_lexical",
                        intent=intent,
                        elapsed_ms=int((time.perf_counter() - t0) * 1000),
                        search_type="LOCAL_LEXICAL",
                        dataset_name=dataset_name,
                        hit_count=len(hits),
                        fallback_used=False,
                    )
                    _query_cache[cache_key] = result
                    return result

        should_fallback = intent in {
            "exact_lookup",
            "fact_lookup",
            "relationship",
            "temporal",
            "summary",
        }
        # In session mode, even open questions go to cognee so the session
        # thread sees every turn — otherwise follow-ups lose continuity.
        if session_id is not None:
            should_fallback = True
        if not should_fallback:
            return KnowledgeQueryResult(
                context="",
                source="miss",
                intent=intent,
                elapsed_ms=int((time.perf_counter() - t0) * 1000),
                search_type=None,
                dataset_name=dataset_name,
                hit_count=0,
                fallback_used=False,
            )

        user = await _resolve_user(user_id)
        context, search_type, hit_count = await _search_cognee(
            query, user, dataset_name, intent, session_id=session_id
        )
        result = KnowledgeQueryResult(
            context=context,
            source="cognee_session" if session_id else (
                "cognee_recall" if context else "miss"),
            intent=intent,
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
            search_type=search_type,
            dataset_name=dataset_name,
            hit_count=hit_count,
            fallback_used=True,
        )
        # Don't cache session turns: a cache hit on a later identical query
        # would skip the cognee call and lose session threading.
        if session_id is None:
            _query_cache[cache_key] = result
        return result
    except Exception as e:  # noqa: BLE001
        print(f"Cognee search error: {e}")
        return KnowledgeQueryResult(
            context="",
            source="error",
            intent=intent,
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
            search_type=None,
            dataset_name=dataset_name,
            hit_count=0,
            fallback_used=False,
        )


async def search(query: str, user_id: str, dataset_name: str) -> str:
    """Retrieve context from a tenant's memory, preserving the old API."""
    return (await query_with_meta(query, user_id, dataset_name)).context


async def visualize(user_id: str, dataset_name: str) -> str:
    """Render one tenant's knowledge graph as a standalone HTML page.

    Scoped to (user, dataset) via cognee's multi-user visualizer so the
    output respects the same per-tenant isolation as add/search — never
    the global graph. Returns the HTML string; raises if the dataset
    doesn't exist for this user (caller maps that to a 404).
    """
    user_id = _tenant(user_id)
    dataset_name = _dataset(dataset_name)
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
    # prune_system drops the relational schema, so the cached "tables exist"
    # flag is now a lie — the next user lookup would hit 'no such table:
    # principals'. Clear it so _ensure_tables rebuilds the schema on next use.
    global _tables_ready
    _tables_ready = False
    _user_cache.clear()
    _local_index_cache.clear()
    _query_cache.clear()
