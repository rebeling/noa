"""Ingestion part — document redaction + Cognee storage/retrieval.

Public surface: IngestionService. Internals: _redaction, _cognee.

Invariant: ingest() redacts before any document reaches Cognee. There
is no code path to Cognee that skips redaction.

Lazy loading: _redaction pulls in presidio and _cognee pulls in cognee,
both heavy. Their imports are deferred to inside the methods so
`import app.ingestion` stays cheap and the server boots fast.
"""

__all__ = ["IngestionService"]


class IngestionService:
    """Document ingestion and knowledge retrieval over Cognee.

    Heavy dependencies (presidio, cognee) load on first method call,
    not at import or construction time.
    """

    async def ingest(
        self, text: str, user_id: str, dataset_name: str = "default"
    ) -> bool:
        """Redact `text`, then write it to Cognee for `user_id`.

        Redaction is mandatory and happens here — callers cannot reach
        Cognee with unredacted text.
        """
        from app.ingestion import _cognee
        from app.ingestion._redaction import redact_text

        redacted = redact_text(text)
        return await _cognee.add_document(redacted, user_id, dataset_name)

    async def query(
        self, query: str, user_id: str, dataset_name: str = "default"
    ) -> str:
        """Search a tenant's knowledge graph."""
        from app.ingestion import _cognee

        return await _cognee.search(query, user_id, dataset_name)
