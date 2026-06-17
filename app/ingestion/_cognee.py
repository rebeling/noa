"""Cognee graph/vector store access — internal to ingestion.

Per-tenant isolation: every add/cognify/search carries user_id +
dataset_name. The safe() sanitizer (in _setup) keeps tenant identifiers
from ever forming path separators or traversal sequences.

Retrieval orchestration lives here; setup/lifecycle is in _setup, the
local lexical fast path in _local_index.
"""

import sqlite3
import time
from dataclasses import dataclass

from app.ingestion import _local_index as local
from app.ingestion import _setup as setup
from app.ingestion._db import cognee_db_path
from app.ingestion._local_index import (
    MAX_CONTEXT_CHARS,
    classify_intent,
    normalize_query,
)
from app.ingestion._setup import (
    ensure_tables,
    get_cognee,
    resolve_user,
    safe,
)

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


# Cached retrieval results, keyed by (safe_user_id, dataset_name, normalized
# query). Bypassed for session turns (see query_with_meta).
_query_cache: dict[tuple[str, str, str], "KnowledgeQueryResult"] = {}


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


def _existing_user_db_id(safe_user_id: str) -> str | None:
    db_path = cognee_db_path()
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


def _invalidate_local_cache(safe_user_id: str, dataset_name: str) -> None:
    prefix = (safe_user_id, dataset_name)
    local.invalidate(safe_user_id, dataset_name)
    for key in [key for key in _query_cache if key[:2] == prefix]:
        _query_cache.pop(key, None)


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
    safe_user_id = safe(user_id)
    dataset_name = safe(dataset_name)
    cognee = get_cognee()
    user = await resolve_user(user_id)
    # self_improvement=False drops remember()'s follow-up reconciliation LLM
    # pass — the main cost in the ~63s ingest. Entity dedup (uuid5 of names)
    # still happens in the base cognify; we only skip the extra improve step,
    # which is the recommended setting for conversational memory.
    await cognee.remember(
        text, dataset_name=dataset_name, user=user, self_improvement=False
    )
    _invalidate_local_cache(safe_user_id, dataset_name)
    return True


# Sessions used to force GRAPH_COMPLETION so a session_id carried conversation
# memory — but that mode runs a second LLM call inside cognee (graph traversal +
# completion) before Noa's own LLM starts: two serial round-trips per turn. We
# already pass only_context=True and throw cognee's generated answer away, so
# paying for it was pure latency. Sessions now use the same fast per-intent
# routing as everything else; session_id is still threaded for the cheap
# session-eligible types and ignored otherwise.


async def _search_cognee(
    query: str,
    user: object,
    dataset_name: str,
    intent: str,
    *,
    use_recall: bool = True,
    session_id: str | None = None,
) -> tuple[str, str, int]:
    cognee = get_cognee()
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

    # Latency-cheap per-intent routing, used for session and non-session turns
    # alike. Only summary/temporal/relationship pay for a graph (and, for the
    # completion types, an LLM) pass — the cases where graph structure helps.
    # Everything else (incl. the open_question default) stays on a fast lexical
    # pass and lets Noa's own LLM write the final answer.
    _INTENT_SEARCH_TYPE = {
        "summary": SearchType.GRAPH_SUMMARY_COMPLETION,
        "temporal": SearchType.TEMPORAL,
        "relationship": SearchType.GRAPH_COMPLETION,
    }
    search_type = _INTENT_SEARCH_TYPE.get(intent, SearchType.CHUNKS_LEXICAL)

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
    return "\n\n".join(parts).strip()[:MAX_CONTEXT_CHARS], search_type.value, len(parts)


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
    safe_user_id = safe(user_id)
    dataset_name = safe(dataset_name)
    intent = classify_intent(query)
    normalized_query = normalize_query(query)
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
        if session_id is None and local.should_try(intent):
            owner_id = _existing_user_db_id(safe_user_id)
            if owner_id is not None:
                index = local.load(safe_user_id, dataset_name, owner_id)
                hits = local.search(index, query)
                if local.hit_is_strong(hits, intent):
                    result = KnowledgeQueryResult(
                        context=local.format_context(hits),
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

        user = await resolve_user(user_id)
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
    dataset_name = safe(dataset_name)
    get_cognee()
    await ensure_tables()
    from cognee.api.v1.visualize import visualize_multi_user_graph
    from cognee.modules.data.methods import get_datasets_by_name

    user = await resolve_user(user_id)
    datasets = await get_datasets_by_name(dataset_name, user.id)
    if not datasets:
        raise ValueError(f"No dataset {dataset_name!r} for this user")
    return await visualize_multi_user_graph([(user, datasets[0])])


async def reset() -> None:
    """Wipe ALL cognee data — every tenant's documents, graph and vectors.

    Global, not per-tenant: this is a dev reset, not a delete-my-dataset.
    Also clears the resolved-user cache so subsequent calls re-create users.
    """
    cognee = get_cognee()
    await ensure_tables()
    await cognee.prune.prune_data()
    await cognee.prune.prune_system(graph=True, vector=True, metadata=True)
    # prune_system drops the relational schema; reset_state clears the cached
    # "tables exist" flag + resolved users so the next call rebuilds them.
    setup.reset_state()
    local.clear()
    _query_cache.clear()
