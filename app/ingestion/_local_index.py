"""Local lexical retrieval — internal to ingestion.

A fast, dependency-free fallback for memory recall: tokenize the documents
cognee has already stored on disk, score them against the query with a cheap
coverage + Jaccard metric, and return the best hits. This dodges the slow
cognee graph/vector call on the easy questions (exact/fact lookups) where a
plain keyword match is good enough.

Pairs with _cognee.py: that module owns cognee setup and the slow path; this
one owns the lexical index and its cache. Intent classification and query
normalization live here because both paths route on them.
"""

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.ingestion._db import cognee_db_path

# Cap retrieved context so it can't blow the downstream LLM prompt.
MAX_CONTEXT_CHARS = 4000

_WORD_RE = re.compile(r"\b[\w]+\b", re.UNICODE)
_STOP_WORDS = {
    "a", "an", "and", "are", "about", "can", "does", "do", "for", "from",
    "give", "how", "in", "is", "me", "of", "on", "please", "the", "to",
    "was", "what", "where", "who", "why",
    "wie", "wo", "wer", "warum", "ist", "sind", "der", "die", "das", "den",
    "dem", "ein", "eine", "einer", "und", "oder", "von", "zu", "im", "am",
    "mit", "mir", "bitte",
}
_LOCAL_MIN_SCORE = 0.45
_LOCAL_TOP_K = 3


@dataclass(frozen=True)
class LocalDocument:
    text: str
    tokens: set[str]
    data_id: str
    path: str


@dataclass(frozen=True)
class LocalHit:
    text: str
    score: float
    data_id: str
    path: str


@dataclass
class LocalIndex:
    docs: list[LocalDocument]


# Tokenized documents, keyed by (safe_user_id, dataset_name).
_local_index_cache: dict[tuple[str, str], LocalIndex] = {}


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in (match.group(0).lower() for match in _WORD_RE.finditer(text))
        if len(token) >= 2 and token not in _STOP_WORDS
    ]


def normalize_query(query: str) -> str:
    return " ".join(tokenize(query))


def classify_intent(query: str) -> str:
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


def _path_from_raw_location(raw_location: str) -> Path | None:
    parsed = urlparse(raw_location or "")
    if parsed.scheme == "file":
        return Path(unquote(parsed.path))
    if not parsed.scheme and raw_location:
        return Path(raw_location)
    return None


def invalidate(safe_user_id: str, dataset_name: str) -> None:
    """Drop the cached index for one tenant (call after an ingest)."""
    _local_index_cache.pop((safe_user_id, dataset_name), None)


def clear() -> None:
    """Drop every cached index (dev reset)."""
    _local_index_cache.clear()


def format_context(hits: list[LocalHit]) -> str:
    parts = []
    for hit in hits:
        text = hit.text.strip()
        if text:
            parts.append(text)
    return "\n\n".join(parts).strip()[:MAX_CONTEXT_CHARS]


def load(safe_user_id: str, dataset_name: str, owner_id: str) -> LocalIndex:
    cache_key = (safe_user_id, dataset_name)
    cached = _local_index_cache.get(cache_key)
    if cached is not None:
        return cached

    db_path = cognee_db_path()
    if not db_path.exists():
        index = LocalIndex(docs=[])
        _local_index_cache[cache_key] = index
        return index

    docs: list[LocalDocument] = []
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
        tokens = set(tokenize(text))
        if text and tokens:
            docs.append(
                LocalDocument(
                    text=text,
                    tokens=tokens,
                    data_id=str(data_id),
                    path=str(path),
                )
            )

    index = LocalIndex(docs=docs)
    _local_index_cache[cache_key] = index
    return index


def search(index: LocalIndex, query: str) -> list[LocalHit]:
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return []

    hits: list[LocalHit] = []
    for doc in index.docs:
        overlap = query_tokens & doc.tokens
        if not overlap:
            continue
        coverage = len(overlap) / len(query_tokens)
        jaccard = len(overlap) / len(query_tokens | doc.tokens)
        score = coverage + (0.2 * jaccard)
        hits.append(
            LocalHit(
                text=doc.text,
                score=score,
                data_id=doc.data_id,
                path=doc.path,
            )
        )

    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[:_LOCAL_TOP_K]


def should_try(intent: str) -> bool:
    return intent in {"fact_lookup", "exact_lookup", "open_question", "summary"}


def hit_is_strong(hits: list[LocalHit], intent: str) -> bool:
    if not hits:
        return False
    if intent == "summary":
        return True
    return hits[0].score >= _LOCAL_MIN_SCORE
